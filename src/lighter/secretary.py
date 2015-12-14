import os, re, nacl, logging, base64
from nacl.public import PublicKey, PrivateKey, Box
from copy import deepcopy
import lighter.util as util

# Regexp to parse simple PEM files
_PEM_RE = re.compile(u"-----BEGIN (.+?)-----\r?\n(.+?)\r?\n-----END \\1-----")

class KeyEncoder(object):
    """
    Base64 NaCL encoder that can also load keys from PEM files
    """
    @staticmethod
    def encode(data):
        return nacl.encoding.Base64Encoder.encode(data)

    @staticmethod
    def decode(data):
        if os.path.exists(data):
            with open(data, "rb") as f:
                contents = f.read()
                matches = _PEM_RE.match(contents)
                if not matches.group(2):
                    raise ValueError("Failed to parse PEM file %s (is absolute path %s readable?)" % (data, path))
                data = matches.group(2)
        
        try:
            return nacl.encoding.Base64Encoder.decode(data)
        except TypeError, e:
            logging.error("Failed to decode key %s (%s)", data, e)

class KeyValue(util.Value):
    """
    Compares deployment keys to be the same if their length is
    """
    def same(self, other):
        return len(self._value) == len(str(other))

def isEnvelope(value):
    return str(value).startswith('ENC[NACL,') and str(value).endswith(']')

def decodePublicKey(key):
    return PublicKey(str(key), encoder=KeyEncoder)

def encodeKey(key):
    return key.encode(encoder=KeyEncoder)

def apply(document, config):
    """
    Generates a deploy key, injects config/master keys and performs the extra deployment time encryption of secrets.
    """
    result = deepcopy(config)
    url = util.rget(document, 'secretary', 'url')
    if not url:
        return

    masterKey = decodePublicKey(util.rget(document, 'secretary', 'master', 'publickey'))

    result['env'] = result.get('env', {})
    result['env']['SECRETARY_URL'] = url
    result['env']['MASTER_PUBLIC_KEY'] = encodeKey(masterKey)

    # Autogenerate a deploy key
    deployKey = PrivateKey.generate()
    result['env']['DEPLOY_PRIVATE_KEY'] = KeyValue(encodeKey(deployKey))
    result['env']['DEPLOY_PUBLIC_KEY'] = KeyValue(encodeKey(deployKey.public_key))

    return result
