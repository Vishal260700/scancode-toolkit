# -*- coding: utf-8 -*-
# -*- Mode: Python; py-ident-offset: 4 -*-
# vim:ts=4:sw=4:et

# Copyright (c) Mário Morgado
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation and/or
# other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""
PyRPM
=====

PyRPM is a pure python, simple to use, module to read information from a RPM
file.
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

from io import BytesIO
import struct

from . import rpmdefs


def find_magic_number(data,):
    """
    Return the start position where the magic number was found in the `data`
    file-like object or None if not found.
    """
    magic_number = rpmdefs.RPM_HEADER_MAGIC_NUMBER
    lmn = len(magic_number)

    base = data.tell()
    while True:
        chunk = data.read(lmn)
        if not chunk or len(chunk) != lmn:
            return
        if chunk == magic_number:
            return base
        base += 1
        data.seek(base)


class Entry(object):
    """
    RPM Header Entry
    """
    def __init__(self, tag, type, value):  # NOQA
        self.tag = tag
        self.type = type
        self.value = value

    def __repr__(self):
        return 'Entry(%r, %r, %r)' % (self.tag, self.type, self.value,)

    @classmethod
    def parse_entry(cls, etag, etype, eoffset, ecount, data_store):

        reader_by_type = {
            rpmdefs.RPM_DATA_TYPE_NULL:            cls.read_null,
            rpmdefs.RPM_DATA_TYPE_CHAR:            cls.read_char,
            rpmdefs.RPM_DATA_TYPE_INT8:            cls.read_int8,
            rpmdefs.RPM_DATA_TYPE_INT16:           cls.read_int16,
            rpmdefs.RPM_DATA_TYPE_INT32:           cls.read_int32,
            rpmdefs.RPM_DATA_TYPE_INT64:           cls.read_int64,
            rpmdefs.RPM_DATA_TYPE_STRING:          cls.read_string,
            rpmdefs.RPM_DATA_TYPE_BIN:             cls.read_bin,
            rpmdefs.RPM_DATA_TYPE_STRING_ARRAY:    cls.read_string_array,
            rpmdefs.RPM_DATA_TYPE_ASN1:            cls.read_bin,
            rpmdefs.RPM_DATA_TYPE_OPENPGP:         cls.read_bin,
            rpmdefs.RPM_DATA_TYPE_I18NSTRING_TYPE: cls.read_string
        }

        reader = reader_by_type[etype]

        # seek to position in store
        data_store.seek(eoffset)
        value = reader(data_store, ecount)

        return Entry(etag, etype, value)

    @classmethod
    def _read(cls, fmt, store):
        size = struct.calcsize(fmt)
        data = store.read(size)
        if len(data) == 0:
            return b''

        unpacked_data = struct.unpack(fmt, data)
        if len(unpacked_data) == 1:
            return unpacked_data[0]
        else:
            return unpacked_data

    @classmethod
    def read_null(cls, store, count):
        return None

    @classmethod
    def read_char(cls, store, count=1):
        return cls._read('!{}c'.format(count), store)

    @classmethod
    def read_int8(cls, store, count):
        return cls._read('!{}B'.format(count), store)

    @classmethod
    def read_int16(cls, store, count):
        return cls._read('!{}H'.format(count), store)

    @classmethod
    def read_int32(cls, store, count):
        return cls._read('!{}I'.format(count), store)

    @classmethod
    def read_int64(cls, store, count):
        return cls._read('!{}Q'.format(count), store)

    @classmethod
    def read_string(cls, store, count):
        string = b''
        while True:
            char = cls.read_char(store, count=1)
            if len(char) == 0 or char == b'\x00':
                # read until '\0'
                break
            string += char
        # We decode as UTF-8 by default and avoid errors with a replacement.
        # UTF-8 should be the standard for RPMs, though for older rpms mileage
        # may vary
        return string and string.decode('utf-8', errors='replace') or None

    @classmethod
    def read_string_array(cls, store, count):
        return [cls.read_string(store, 1) for _ in range(count)]

    @classmethod
    def read_bin(cls, store, count):
        return cls._read('!{}s'.format(count), store)

    @classmethod
    def read_i18n_string(cls, store, count):
        return cls._read_('!{}s'.format(count), store)


class Header(object):
    """
    RPM Header Structure
    """

    def __init__(self, header, entries_index, store):
        self.store = store
        self.entries = []
        entryfmt = '!llll'

        for entry_index in entries_index:
            """
            Each entry data is in the form
             [4bytes][4bytes][4bytes][4bytes]
              TAG     TYPE    OFFSET  COUNT
            """
            entry_data = struct.unpack(entryfmt, entry_index)
            if not entry_data:
                continue
            etag, etype, eoffset, ecount = entry_data
            if not (rpmdefs.RPMTAG_MIN_NUMBER <= etag <= rpmdefs.RPMTAG_MAX_NUMBER):
                # TODO: log me!!!
                continue
            if etag not in rpmdefs.RPMTAGS:
                # TODO: log me!!!
                continue
            entry = Entry.parse_entry(etag, etype, eoffset, ecount , store)
            if entry:
                self.entries.append(entry)


class RPMError(BaseException):
    pass


class RPM(object):

    def __init__(self, rpm):
        """
        Create a new RPM from an `rpm` file-like object.
        """
        if hasattr(rpm, 'read'):  # if it walk like a duck..
            self.rpmfile = rpm
        else:
            raise ValueError(
                'Expected file-like object, but got: %r' % (type(rpm),))
        self.is_binary = True
        self.headers = []
        self.entries_by_tag = {}

        self.read_lead()
        offset = self.read_sigheader()
        self.read_headers(offset)

    def read_lead(self):
        """
        Read the rpm lead section

        struct rpmlead {
           unsigned char magic[4];
           unsigned char major, minor;
           short type;
           short archnum;
           char name[66];
           short osnum;
           short signature_type;
           char reserved[16];
           } ;
        """
        lead_fmt = '!4sBBhh66shh16s'
        data = self.rpmfile.read(96)
        value = struct.unpack(lead_fmt, data)

        magic_num = value[0]
        package_type = value[3]

        if magic_num != rpmdefs.RPM_LEAD_MAGIC_NUMBER:
            raise RPMError('Wrong magic number: this is not a RPM file')

        if package_type == 0:
            self.is_binary = True
        elif package_type == 1:
            self.is_binary = False
        else:
            raise RPMError('Wrong package type: should either 0 (binary RPM) or 1 (source RPM).')

    def read_sigheader(self):
        """
        Read signature header

        ATN: this will not return any usefull information
        besides the file offset
        """
        start = find_magic_number(self.rpmfile)
        if not start:
            raise RPMError('invalid RPM file, signature header not found')
        # return the offset after the magic number
        return start + 3

    def read_header(self, header):
        """
        Read the header-header section
        [3bytes][1byte][4bytes][4bytes][4bytes]
          MN      VER   UNUSED  IDXNUM  STSIZE
        """
        if not len(header) == 16:
            raise RPMError('invalid header size')

        headerfmt = '!3sc4sll'
        header = struct.unpack(headerfmt, header)
        magic_num = header[0]
        if magic_num != rpmdefs.RPM_HEADER_MAGIC_NUMBER:
            raise RPMError('invalid RPM header')
        return header

    def read_headers(self, offset):
        """
        Read information headers
        """
        # lets find the start of the header
        self.rpmfile.seek(offset)
        start = find_magic_number(self.rpmfile)
        # go back to the begining of the header
        self.rpmfile.seek(start)
        header = self.rpmfile.read(16)
        header = self.read_header(header)
        entries_index = []
        entries_count = header[3]
        for _entry in range(entries_count):
            entry_index = self.rpmfile.read(16)
            entries_index.append(entry_index)
        store = BytesIO(self.rpmfile.read(header[4]))
        header = Header(header, entries_index, store)
        self.headers.append(header)

        for header in self.headers:
            for entry in header.entries:
                self.entries_by_tag[entry.tag] = entry

    def __iter__(self):
        for entry in self.entries_by_tag.values():
            yield entry

    def __getitem__(self, item):
        return self.get_entry_value(item)

    def get_entry_value(self, tag):
        """
        Return the value of an Entry for the `tag` number or None.
        """
        entry = self.entries_by_tag.get(tag)
        if not entry or not entry.value:
            return
        return entry.value

    @property
    def name(self):
        return self.get_entry_value(rpmdefs.RPMTAG_NAME)

    @property
    def epoch(self):
        """
        Return a epoch or None for the epoch 0 and if no epoch is defined.
        """
        epoch = self.get_entry_value(rpmdefs.RPMTAG_EPOCH)
        if not epoch:
            return
        if isinstance(epoch, (tuple, list)):
            epoch = epoch[0]
        if not isinstance(epoch, str):
            epoch = str(epoch)
        if not epoch or epoch == '0':
            return
        if epoch.lower() == 'none':
            return
        return epoch or None

    @property
    def version(self):
        return self.get_entry_value(rpmdefs.RPMTAG_VERSION)

    @property
    def release(self):
        return self.get_entry_value(rpmdefs.RPMTAG_RELEASE)

    @property
    def arch(self):
        return self.get_entry_value(rpmdefs.RPMTAG_ARCH)

    @property
    def os(self):
        return self.get_entry_value(rpmdefs.RPMTAG_OS)

    @property
    def summary(self):
        return self.get_entry_value(rpmdefs.RPMTAG_SUMMARY)

    @property
    def description(self):
        # the full description is often a long text
        return self.get_entry_value(rpmdefs.RPMTAG_DESCRIPTION)

    @property
    def distribution(self):
        return self.get_entry_value(rpmdefs.RPMTAG_DISTRIBUTION)

    @property
    def vendor(self):
        return self.get_entry_value(rpmdefs.RPMTAG_VENDOR)

    @property
    def packager(self):
        return self.get_entry_value(rpmdefs.RPMTAG_PACKAGER)

    @property
    def license(self):
        return self.get_entry_value(rpmdefs.RPMTAG_LICENSE)

    @property
    def patch(self):
        return self.get_entry_value(rpmdefs.RPMTAG_PATCH)

    @property
    def group(self):
        return self.get_entry_value(rpmdefs.RPMTAG_GROUP)

    @property
    def url(self):
        return self.get_entry_value(rpmdefs.RPMTAG_URL)

    @property
    def dist_url(self):
        return self.get_entry_value(rpmdefs.RPMTAG_DISTURL)

    @property
    def source_rpm(self):
        return self.get_entry_value(rpmdefs.RPMTAG_SOURCERPM)

    @property
    def source_package(self):
        return self.get_entry_value(rpmdefs.RPMTAG_SOURCEPACKAGE)

    @property
    def package(self):
        return '-'.join([self.name, self.version])

    @property
    def filename(self):
        name = '-'.join([self.package, self.release])
        arch = self.arch
        if self.is_binary:
            ext = 'rpm'
        else:
            ext = 'src.rpm'
        return '.'.join([name, arch, ext])

    def get_tags(self):
        """
        returns a dict of tags, keyed by name
        """
        tgs = {}
        for tagid, tagname in rpmdefs.RPMTAGS.items():
            tag = self[tagid]
            if not tag or tag == 'None':
                tag = None
            tgs[tagname] = tag
        return tgs

    def to_dict(self):
        return dict(
            name=self.name,
            epoch=self.epoch,
            version=self.version,
            release=self.release,
            arch=self.arch,
            os=self.os,
            summary=self.summary,
            description=self.description,
            distribution=self.distribution,
            vendor=self.vendor,
            packager=self.packager,
            license=self.license,
            group=self.group,
            url=self.url,
            dist_url=self.dist_url,
            source_rpm=self.source_rpm,
            source_package=self.source_package,
            is_binary=self.is_binary,
        )
