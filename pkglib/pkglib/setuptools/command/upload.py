import os
import socket
import platform
from urllib2 import urlopen, Request, HTTPError
from base64 import standard_b64encode
import urlparse
import cStringIO as StringIO
from hashlib import md5

from distutils.command.upload import upload as _upload
from distutils.spawn import spawn
from distutils import log

from base import CommandMixin


class upload(_upload, CommandMixin):
    """ Wrapper around upload command to raise correct return codes
        to the system.
    """
    __doc__ = _upload.__doc__
    _ok_status_codes = [200]

    def run(self):
        self._run(_upload, 'upload')

    def upload_file(self, command, pyversion, filename):
        # Makes sure the repository URL is compliant
        schema, netloc, url, params, query, fragments = \
            urlparse.urlparse(self.repository)

        if params or query or fragments:
            raise AssertionError("Incompatible url %s" % self.repository)

        if schema not in ('http', 'https'):
            raise AssertionError("unsupported schema " + schema)

        # Sign if requested
        if self.sign:
            gpg_args = ["gpg", "--detach-sign", "-a", filename]
            if self.identity:
                gpg_args[2:2] = ["--local-user", self.identity]
            spawn(gpg_args,
                  dry_run=self.dry_run)

        # Fill in the data - send all the meta-data in case we need to
        # register a new release
        f = open(filename, 'rb')
        try:
            content = f.read()
        finally:
            f.close()
        meta = self.distribution.metadata
        data = {
            # action
            ':action': 'file_upload',
            'protcol_version': '1',

            # identify release
            'name': meta.get_name(),
            'version': meta.get_version(),

            # file content
            'content': (os.path.basename(filename), content),
            'filetype': command,
            'pyversion': pyversion,
            'md5_digest': md5(content).hexdigest(),

            # additional meta-data
            'metadata_version': '1.0',
            'summary': meta.get_description(),
            'home_page': meta.get_url(),
            'author': meta.get_contact(),
            'author_email': meta.get_contact_email(),
            'license': meta.get_licence(),
            'description': meta.get_long_description(),
            'keywords': meta.get_keywords(),
            'platform': meta.get_platforms(),
            'classifiers': meta.get_classifiers(),
            'download_url': meta.get_download_url(),
            # PEP 314
            'provides': meta.get_provides(),
            'requires': meta.get_requires(),
            'obsoletes': meta.get_obsoletes(),
            }
        comment = ''
        if command == 'bdist_rpm':
            dist, version, id = platform.dist()
            if dist:
                comment = 'built for %s %s' % (dist, version)
        elif command == 'bdist_dumb':
            comment = 'built for %s' % platform.platform(terse=1)
        data['comment'] = comment

        if self.sign:
            data['gpg_signature'] = (os.path.basename(filename) + ".asc",
                                     open(filename + ".asc").read())

        username, password = self.request_credentials(self.repository)

        # set up the authentication
        auth = "Basic " + standard_b64encode(username + ":" + password)

        # Build up the MIME payload for the POST data
        boundary = '--------------GHSKFJDLGDS7543FJKLFHRE75642756743254'
        sep_boundary = '\n--' + boundary
        end_boundary = sep_boundary + '--'
        body = StringIO.StringIO()
        for key, value in data.items():
            # handle multiple entries for the same name
            if not isinstance(value, list):
                value = [value]
            for value in value:
                if isinstance(value, tuple):
                    fn = ';filename="%s"' % value[0]
                    value = value[1]
                else:
                    fn = ""

                body.write(sep_boundary)
                body.write('\nContent-Disposition: form-data; name="%s"' % key)
                body.write(fn)
                body.write("\n\n")
                body.write(value)
                if value and value[-1] == '\r':
                    body.write('\n')  # write an extra newline (lurve Macs)
        body.write(end_boundary)
        body.write("\n")
        body = body.getvalue()

        self.announce("Submitting %s to %s" % (filename, self.repository), log.INFO)

        # build the Request
        headers = {'Content-type':
                        'multipart/form-data; boundary=%s' % boundary,
                   'Content-length': str(len(body)),
                   'Authorization': auth}

        request = Request(self.repository, data=body,
                          headers=headers)
        # send the data
        try:
            result = urlopen(request)
            status = result.getcode()
            reason = result.msg
            if self.show_response:
                msg = '\n'.join(('-' * 75, result.read(), '-' * 75))
                self.announce(msg, log.INFO)
        except socket.error, e:
            self.announce(str(e), log.ERROR)
            return
        except HTTPError, e:
            status = e.code
            reason = e.msg

        if status == 200:
            self.store_credentials(username, password)
            self.announce('Server response (%s): %s' % (status, reason),
                          log.INFO)
        else:
            self.announce('Upload failed (%s): %s' % (status, reason),
                          log.ERROR)