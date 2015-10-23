#!/usr/bin/env python
import os, sys, optparse, logging
from pprint import pprint
import yaml, urllib2, json, urlparse, base64,ntpath

def parsebool(value):
    truevals = set(['true', '1'])
    falsevals = set(['false', '0'])
    stripped = str(value).lower().strip()
    if stripped in truevals:
        return True
    if stripped in falsevals:
        return False

    logging.error("Invalid boolean value '%s'", value)
    sys.exit(1)

def parseint(value):
    try:
        return int(value)
    except:
        logging.error("Invalid integer value '%s'", value)
        sys.exit(1)

def parselist(value):
    return filter(bool, value.split(','))

def merge_two_dicts(a, b):
    result = {}

    for key in set(a.keys() + b.keys()):
        aval = a.get(key)
        bval = b.get(key)
        if isinstance(aval, dict) or isinstance(bval, dict):
            result[key] = merge_two_dicts(aval or {}, bval or {})
        else:
            result[key] = bval or aval

    return result

def compare_service_versions(nextVersion, prevVersion, path=''):
    if isinstance(nextVersion, dict):
        for key, value in nextVersion.items():
            keypath = path + '/' + key
            if key not in prevVersion:
                logging.debug("New key found %s", keypath)
                return False
            if not compare_service_versions(value, prevVersion[key], keypath):
                return False
    elif isinstance(nextVersion, list):
        if len(nextVersion) != len(prevVersion):
            logging.debug("List have changed at %s", path)
            return False
        for nextValue, prevValue in zip(sorted(nextVersion), sorted(prevVersion)):
            if not compare_service_versions(nextValue, prevValue, path):
                return False
    elif nextVersion != prevVersion:
        logging.debug("Value has changed at %s (%s != %s)", path, nextVersion, prevVersion)
        return False
    return True

def merge_dicts(*dicts):
    result = {}
    for dts in dicts:
        result = merge_two_dicts(result, dts)

    return result

def urlunparse(data):
    """
    Modified from urlparse.urlunparse to support file://./path/to urls
    """
    scheme, netloc, url, params, query, fragment = data
    if params:
        url = "%s;%s" % (url, params)
    if netloc:
        url = '//' + (netloc or '') + url
    if scheme:
        url = scheme + ':' + url
    if query:
        url = url + '?' + query
    if fragment:
        url = url + '#' + fragment
    return url

def build_request(url, data=None, headers={}, method='GET'):
    parsed_url = urlparse.urlparse(url)
    parts = list(parsed_url[0:6])
    parts[1] = ('@' in parts[1]) and parts[1].split('@')[1] or parts[1]

    request = urllib2.Request(urlunparse(parts), data, headers)
    request.get_method = lambda: method

    if parsed_url.username is not None and parsed_url.password is not None:
        # You need the replace to handle encodestring adding a trailing newline
        # (https://docs.python.org/2/library/base64.html#base64.encodestring)
        base64string = base64.encodestring('%s:%s' % (parsed_url.username, parsed_url.password)).replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)

    return request

def parse_file(file):
    with open(file, 'r') as stream:
        doc = yaml.load(stream)

        g_file = ntpath.split(file)[0] + '/globals.yml'
        with open(g_file, 'r') as g_stream:
            g_doc = yaml.load(g_stream)
            maven_content = merge_two_dicts(doc['maven'], g_doc['maven'])

            repository = maven_content['repository']
            url = '{0}/{1}/{2}/{3}/{2}-{3}.json'.format(repository, maven_content['groupid'].replace('.', '/'), maven_content['artifactid'], maven_content['version'])
            response = urllib2.urlopen(build_request(url)).read()
            json_response = json.loads(response)

            merged_content = merge_dicts(json_response, doc['override'], doc['variables'], g_doc['variables'])

        return merged_content

def get_marathon_url(url, id):
    return url.rstrip('/') + '/v2/apps/' + id.strip('/') + '?force=true'

def get_marathon_app(url):
    try:
        response = urllib2.urlopen(build_request(url))
        content = response.read()
        return json.loads(content)['app']
    except Exception, e:
        logging.debug(str(e))
        return {}

if __name__ == '__main__':
    parser = optparse.OptionParser(
        usage='lighter.py [options]... service.yml service2.yml',
        description='Marathon deployment tool')

    parser.add_option('-m', '--marathon', dest='marathon', help='Marathon url, e.g. "http://marathon-01:8080/"',
                      default=os.environ.get('MARATHON_URL', ''))

    parser.add_option('-v', '--verbose', dest='verbose', help='Increase logging verbosity',
                      action="store_true", default=parsebool(os.environ.get('VERBOSE', False)))

    (options, args) = parser.parse_args()

    if options.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    if not options.marathon:
        parser.print_help()
        sys.exit(1)

    for file in args:
        logging.info("Processing %s", file)
        nextVersion = parse_file(file)
        appurl = get_marathon_url(options.marathon, nextVersion['id'])

        # See if service config has changed
        prevVersion = get_marathon_app(appurl)
        if compare_service_versions(nextVersion, prevVersion):
            logging.debug("Service already deployed with same config: %s", file)

        # Deploy new service config
        logging.debug("Deploying %s", file)
        serialized_json = json.dumps(nextVersion)
        request = urllib2.Request(appurl, serialized_json, {'Content-Type': 'application/json'})
        request.get_method = lambda: 'PUT'
        response = urllib2.urlopen(request)
