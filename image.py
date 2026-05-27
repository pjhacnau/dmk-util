#!/usr/bin/python3

(JV1, JV3, DMK, HARD, NOTSUPP) = range(5)

from collections import namedtuple
import logging
from os import path
import string
import struct
import sys

Geometry = namedtuple('Geometry', 'sides tracks')

logger = logging.getLogger(__name__)

def determine_format(filename):
    """
    What format disk image are we looking at?  Approach:

    - First check for JV1.  As this has to be of size (256 * 10 * {tracks})
      where {tracks} is usually 35 or 40, and JV3 and DMK are going to
      be larger, a simple size check gets used

    - Now check for  DMK as the opening 16 byte header should be fairly
      easy to decode.  Only "virtual" format supported.

    - Finally, look for JV3.

    - If we get here, not supported.
    """

    flen = path.getsize(filename)
    if flen <= JV1_Image.TRACKS * 40:
        return JV1

    with open(filename, 'rb') as f:
        f.seek(0)
        try:
            h = Hard_Image.read_header(f)
            if h.id1 == 0x56 and h.id2 == 0xcb:
                return HARD
        except:
            pass

        f.seek(0)
        hdr = DMK_Image.read_header(f)
        if (hdr.wp == 0) or (hdr.wp == 0xff):
            if hdr.fmt == 0x12345678:
                print("No Physical DMK")
                return NOTSUPP
            if hdr.fmt == 0:
                if (hdr.tracklen >= 16) and (hdr.tracklen <= 0x4000):
                    return DMK

        f.seek(JV3_Image.HEADER_ARRAY, 0)
        (c,) = struct.unpack('B', f.read(1))
        if (c == 0) or (c == 0xff):
            return JV3


    return NOTSUPP

class FormatError(Exception):
    pass


class Image(object):

    def __init__(self, format, f):
        self._format = format
        self._file = f
        self._geo = None

    def format(self):
        return self._format

    def _setGeometry(self, g):
        self._geo = g

    @property
    def tracks(self):
        return 0 if self._geo is None else self._geo.tracks

    @property
    def sides(self):
        return 0 if self._geo is None else self._geo.sides

class JV1_Image(Image):

    SIDES = 1
    TRACKS = 35
    SECTORS_PER_TRACK = 10
    SECTOR_SIZE = 256
    TRACK_SIZE = SECTORS_PER_TRACK * SECTOR_SIZE
    def __init__(self, f):
        Image.__init__(self, 'JV1', f)
        Image._setGeometry(self, Geometry(JV1_Image.SIDES,
                                          JV1_Image.TRACKS))

    def read_track(self, track):
        offset = track * JV1_Image.TRACK_SIZE
        self._file.seek(offset)
        return self._file.read(JV1_Image.TRACK_SIZE)

    def read_sector(self, track, sector):

        #
        # As JV1 is fixed-format 256 byte sectors, 10 sectors per track,
        # calculation is fairly simple
        #
        offset = (track * JV1_Image.TRACK_SIZE) + \
            (sector * JV1_Image.SECTOR_SIZE)
        self._file.seek(offset)
        return self._file.read(JV1_Image.SECTOR_SIZE)

class JV3_Image(Image):

    SECTOR_HEADERS = 2901
    HEADER_SIZE = 3
    HEADER_ARRAY = SECTOR_HEADERS * HEADER_SIZE
    Header = namedtuple('Header', 'track sector flags')

    # JV3 flag bit definitions
    FLAG_SIDE = 0x10         # Side 1 indicator
    FLAG_ERROR = 0x20        # Error indicator
    FLAG_ENCRYPTED = 0x40    # Encrypted sector
    FLAG_SIZE_MASK = 0x03    # Size bits
    FLAG_DAM = 0x08          # Data Address Mark type
    FLAG_SIDE_CRC_ERR = 0x80 # Side/CRC error

    @classmethod
    def iToO(cls, index):
        return index * JV3_Image.HEADER_SIZE

    def __init__(self, f, use_f8 = False):
        Image.__init__(self, 'JV3', f)
        f.seek(0, 0)
        #
        # Ok
        #
        headers = f.read(self.HEADER_ARRAY)
        self._headers = list()
        lastTrack = 0
        lastSector = 0
        sides = 1
        for i in range(self.SECTOR_HEADERS):
            idx = self.iToO(i)
            idx_1 = self.iToO(i + 1)
            header = JV3_Image.Header._make(struct.unpack('BBB', headers[idx:idx_1]))
            if header.track > lastTrack:
                lastTrack = header.track
            if header.sector > lastSector:
                lastSector = header.sector
            if (header.flags != 0xff) and (header.flags & 0x10) != 0:
                sides = 2

            self._headers.append(header)

        self._use_f8 = use_f8

        Image._setGeometry(self, Geometry(sides,
                                          lastTrack + 1))
    @classmethod
    def _sec_size(cls, hdr, use_f8):
        '''
        Calculate sector size based on flags.
        Returns size in bytes: 128, 256, 512, or 1024
        '''
        if ((hdr.flags & 0x60) == 0x20) and use_f8: # empty and care
            ibm_sz = (hdr.flags & cls.FLAG_SIZE_MASK) ^ 2
        else:
            ibm_sz = (hdr.flags & cls.FLAG_SIZE_MASK) ^ 1

        return 128 * pow(2, ibm_sz) if ibm_sz <= 2 else 1024

    def read_sector(self, track, sector):
        '''
        Read a single sector by track and sector number.
        Returns sector data or None if not found.
        '''
        i = 0
        sz = 0
        for h in self._headers:
            if (h.track == track) and (h.sector == sector):
                break
            i += 1
            sz += self._sec_size(h, self._use_f8)

        if i == 2901:
            return None

        #print ("t {} s {} at entry {} flags {:x}".format(track, sector, i, f))
        h = self._headers[i]
        this_sz = self._sec_size(h, self._use_f8)
        if False: #(f & 0x60) == 0x20:
            return struct.pack('B', 0) * this_sz
        else:
            self._file.seek((self.HEADER_ARRAY + 1) + sz, 0)
            return self._file.read(this_sz)
    def read_track(self, track):
        '''
        Read all sectors from a specified track.
        Returns concatenated sector data as bytes.
        '''
        track_data = bytearray()

        # Find all sectors on this track
        sector_numbers = set()
        for h in self._headers:
            if h.track == track and h.flags != 0xff:
                sector_numbers.add(h.sector)

        # Sort sectors and read them
        for sector in sorted(sector_numbers):
            sector_data = self.read_sector(track, sector)
            if sector_data is not None:
                track_data.extend(sector_data)

        return bytes(track_data) if track_data else None

    def get_sector_info(self, track, sector):
        '''
        Get detailed information about a specific sector.
        Returns dictionary with sector metadata or None if not found.
        '''
        for i, h in enumerate(self._headers):
            if (h.track == track) and (h.sector == sector):
                return {
                    'track': h.track,
                    'sector': h.sector,
                    'flags': h.flags,
                    'side': 1 if (h.flags & self.FLAG_SIDE) else 0,
                    'has_error': (h.flags & self.FLAG_ERROR) != 0,
                    'encrypted': (h.flags & self.FLAG_ENCRYPTED) != 0,
                    'sector_size': self._sec_size(h),
                    'header_index': i,
                    'size_code': h.flags & self.FLAG_SIZE_MASK,
                    'dam_type': 'FB' if (h.flags & self.FLAG_DAM) else 'F8',
                }
        return None

    def get_geometry(self):
        '''
        Return detailed geometry information.
        '''
        # Count actual sectors per track (on side 0)
        sectors_per_track = 0
        for h in self._headers:
            if (h.track == 0) and ((h.flags & self.FLAG_SIDE) == 0) and (h.flags != 0xff):
                sectors_per_track += 1

        # Calculate total data size
        total_data_size = sum(self._sec_size(h) for h in self._headers if h.flags != 0xff)

        return {
            'sides': self.sides,
            'tracks': self.tracks,
            'sectors_per_track': sectors_per_track,
            'total_sectors': len([h for h in self._headers if h.flags != 0xff]),
            'header_size': self.HEADER_ARRAY,
            'total_data_size': total_data_size,
            'format': 'JV3'
        }

    def validate_header(self):
        '''
        Validate JV3 image integrity.
        Returns dictionary with validation results.
        '''
        # Check for reasonable track/sector values
        valid_tracks = all(h.track < 256 for h in self._headers if h.flags != 0xff)
        valid_sectors = all(h.sector < 256 for h in self._headers if h.flags != 0xff)

        # Check for at least some valid sectors
        valid_sectors_exist = len([h for h in self._headers if h.flags != 0xff]) > 0

        # Check header termination
        proper_termination = all(h.flags == 0xff for h in self._headers[self.SECTOR_HEADERS - 10:])

        return {
            'valid_tracks': valid_tracks,
            'valid_sectors': valid_sectors,
            'sectors_exist': valid_sectors_exist,
            'proper_termination': proper_termination,
            'total_headers': self.SECTOR_HEADERS,
            'used_slots': len([h for h in self._headers if h.flags != 0xff])
        }

    def list_sectors(self, track=None):
        '''
        List all sectors, optionally filtered by track.
        Returns list of sector information dictionaries.
        '''
        sectors_list = []

        for h in self._headers:
            if h.flags == 0xff:
                continue

            if track is not None and h.track != track:
                continue

            sectors_list.append({
                'track': h.track,
                'sector': h.sector,
                'side': 1 if (h.flags & self.FLAG_SIDE) else 0,
                'size': self._sec_size(h),
                'flags': '0x{:02x}'.format(h.flags),
                'error': (h.flags & self.FLAG_ERROR) != 0,
            })

        return sorted(sectors_list, key=lambda x: (x['track'], x['side'], x['sector']))

    def get_sector_data_offset(self, track, sector):
        '''
        Get the file offset where sector data begins.
        Useful for debugging or direct file access.
        '''
        offset = 0
        for h in self._headers:
            if (h.track == track) and (h.sector == sector):
                return self.HEADER_ARRAY + 1 + offset
            if h.flags != 0xff:
                offset += self._sec_size(h)

        return None

class DMK_Image(Image):

    VDISK_HDR = 16
    IDAM_SIZE = 128
    Header = namedtuple('Header', 'wp tracks tracklen flags fmt')
    HDRSTR = '<BBHB7xL'

    # Flag definitions
    FLAG_SINGLE_SIDED = 0x10
    FLAG_DOUBLE_DENSITY = 0x40
    FLAG_IGNORE_DENSITY = 0x80
    FLAG_SINGLE_DENSITY = 0x00

    @classmethod
    def read_header(cls, f) -> Header:
        return cls.Header._make(struct.unpack(cls.HDRSTR,
                                              f.read(cls.VDISK_HDR)))

    def __init__(self, f):
        Image.__init__(self, 'DMK', f)
        f.seek(0, 0)
        hdr = DMK_Image.read_header(f)
        self._wp = hdr.wp
        self._ntracks = hdr.tracks
        self._tracklen = hdr.tracklen
        self._sides = 1 if (hdr.flags & 0x10) else 2
        self._sden = (hdr.flags & 0x40) != 0
        self._ignden = (hdr.flags & 0x80) != 0
        self._curtrack = self._curside = -1
        self._trackstart = 16
        self._trackheader_sz = 0x80
        Image._setGeometry(self, Geometry(self._sides,
                                          self._ntracks))

    def _parse_idam_list(self, track_data):
        '''
        Parse the IDAM (Index Data Address Mark) list from track header.
        Returns list of IDAM offsets and sector information.
        '''
        idam_list = []
        idam_bytes = struct.unpack('<' + 'H' * int(self.IDAM_SIZE / 2),
                                   track_data[:self.IDAM_SIZE])

        for idam_offset in idam_bytes:
            if idam_offset == 0:
                break

            # Extract actual offset (lower 14 bits)
            actual_offset = idam_offset & 0x3fff
            # Check if this is a data mark (bit 15 = 1 means data mark)
            is_data_mark = (idam_offset & 0x8000) != 0

            idam_list.append({
                'offset': actual_offset,
                'is_data_mark': is_data_mark
            })

        return idam_list

    def _parse_sector_header(self, track_data, idam_offset):
        '''
        Parse sector header information at given offset.
        Returns dictionary with track, sector, size, and CRC info.
        '''
        if idam_offset + 7 > len(track_data):
            return None

        try:
            # FE marker should be at idam_offset
            if track_data[idam_offset] != 0xfe:
                return None

            (track, head, sector, size_code, crc) = \
                struct.unpack('<BBBBH', track_data[idam_offset + 1:idam_offset + 7])

            # Calculate sector size: 128 * 2^size_code
            sector_size = 128 * (1 << size_code) if size_code <= 3 else 0

            return {
                'track': track,
                'head': head,
                'sector': sector,
                'size_code': size_code,
                'sector_size': sector_size,
                'crc': crc
            }
        except:
            return None

    def _find_sector_data_offset(self, track_data, idam_list, target_sector):
        '''
        Find the data offset for a specific sector.
        Returns offset and size, or None if not found.
        '''
        logger.debug("find_sector_data_offset()")

        for i, idam in enumerate(idam_list):
            sector_info = self._parse_sector_header(track_data, idam['offset'])
            if sector_info is None:
                continue
            logger.debug(sector_info)
            if sector_info['sector'] == target_sector:
                # Now it gets . . . "interesting" according to:
                # https://retrocomputing.stackexchange.com/questions/15282/understanding-the-dmk-disk-image-file-format-used-by-trs-80-emulators
                # you keep going till you find an 0xfb of 0xf8 marker,
                # mirroring how a _real_ disk would work.
                data_offset = idam['offset'] + 7 + 3
                while (track_data[data_offset] != 0xfb) and (track_data[data_offset] != 0xf8):
                    data_offset += 1
                return data_offset + 1, sector_info['sector_size']

        return None

    def read_track(self, tracknum, raw=False):
        '''
        Read raw track data from specified track number.
        If raw=False, returns track data without IDAM list.
        '''
        logger.info('read_track({}, {})'.format(tracknum, raw))
        loc = self._trackstart + (tracknum * self._tracklen)
        self._file.seek(loc, 0)
        track_data = self._file.read(self._tracklen)

        if len(track_data) != self._tracklen:
            raise FormatError("Expected {} bytes, got {}".format(self._tracklen, len(track_data)))

        if raw:
            return track_data
        else:
            # Return data after IDAM list
            return track_data[self.IDAM_SIZE:]

    def old_read_sector(self, tracknum, sector):
        print("Read track {} sector {}".format(tracknum, sector))
        track = self.read_track(tracknum, raw=True)
        if len(track) != self._tracklen:
            print("Expected {} got {}".format(self._tracklen, len(track)))
            sys.exit(-1)

        idamps = struct.unpack('<' + 'H' * int(self._trackheader_sz / 2),
                               track[:self._trackheader_sz])
        for idamp in idamps:
            if idamp == 0:
                break
            idamp &= 0x3fff
            p = track[idamp]
            if p != 0xfe:
                continue
            (t,sd,sec,bc,crc) = \
                struct.unpack('<BBBBH', track[idamp + 1:idamp + 7])
            print("0x{:x} -> {} {}".format(idamp, sec, bc))
            if sec == sector:
                return track[idamp + 7:idamp + 263]

    def read_sector(self, tracknum, sector):
        """
        Read a single sector from specified track.
        Returns sector data or None if not found.
        """
        logger.debug("read_sector({}, {})".format(tracknum, sector))
        track_data = self.read_track(tracknum, raw=True)
        if track_data is None:
            return None

        idam_list = self._parse_idam_list(track_data)
        logger.debug("IDAM list has {} entries".format(len(idam_list)))
        result = self._find_sector_data_offset(track_data, idam_list, sector)

        if result is None:
            return None
        logger.debug("({:x}, {:x})".format(*result))
        data_offset, sector_size = result

        if data_offset + sector_size > len(track_data):
            return None

        return track_data[data_offset:data_offset + sector_size]

    def list_sectors(self, tracknum):
        """
        List all sectors on a specified track.
        Returns list of sector information dictionaries.
        """
        track_data = self.read_track(tracknum, raw=True)
        if track_data is None:
            return []

        sectors = []
        idam_list = self._parse_idam_list(track_data)

        for idam in idam_list:
            sector_info = self._parse_sector_header(track_data, idam['offset'])
            if sector_info is None:
                continue

            sectors.append({
                'track': sector_info['track'],
                'head': sector_info['head'],
                'sector': sector_info['sector'],
                'size_code': sector_info['size_code'],
                'sector_size': sector_info['sector_size'],
                'crc': '0x{:04x}'.format(sector_info['crc']),
                'idam_offset': idam['offset'],
                'is_data_mark': idam['is_data_mark']
            })

        return sectors

    def get_sector_info(self, tracknum, sector):
        """
        Get detailed information about a specific sector.
        Returns dictionary with sector metadata or None if not found.
        """
        track_data = self.read_track(tracknum, raw=True)
        if track_data is None:
            return None

        idam_list = self._parse_idam_list(track_data)

        for idam in idam_list:
            sector_info = self._parse_sector_header(track_data, idam['offset'])
            if sector_info is None:
                continue

            if sector_info['sector'] == sector:
                return {
                    'track': sector_info['track'],
                    'head': sector_info['head'],
                    'sector': sector_info['sector'],
                    'size_code': sector_info['size_code'],
                    'sector_size': sector_info['sector_size'],
                    'crc': '0x{:04x}'.format(sector_info['crc']),
                    'file_offset': self._trackstart + (tracknum * self._tracklen) + idam['offset'],
                    'data_offset': self._trackstart + (tracknum * self._tracklen) + idam['offset'] + 10
                }

        return None

    def get_geometry(self):
        """
        Return detailed geometry information from DMK header.
        """
        # Calculate sectors per track from track length
        # This is approximate since sector sizes can vary
        sectors_per_track = 0

        # Sample first track to count sectors
        if self._ntracks > 0:
            track_data = self.read_track(0, raw=True)
            if track_data is not None:
                idam_list = self._parse_idam_list(track_data)
                sectors_per_track = len(idam_list)

        return {
            'sides': self._sides,
            'tracks': self._ntracks,
            'track_length': self._tracklen,
            'sectors_per_track': sectors_per_track,
            'sector_size': 256,  # Common size
            'density': 'Double' if self._sden else 'Single',
            'write_protected': self._wp,
            'ignore_density': self._ignden,
            'header_size': self.VDISK_HDR,
            'idam_size': self.IDAM_SIZE,
            'format': 'DMK Virtual'
        }

    def validate_header(self):
        '''
        Validate DMK image header and structure.
        Returns dictionary with validation results.
        '''
        checks = {
            'valid_write_protect': self._wp in [0x00, 0xff],
            'tracks_reasonable': 0 < self._ntracks <= 256,
            'track_length_reasonable': (16 <= self._tracklen <= 0x4000),
            'track_length_multiple_128': (self._tracklen % 128) == 0,
            'write_protected': self._wp,
            'single_sided': self._sides == 1,
            'double_sided': self._sides == 2,
            'double_density': self._sden,
            'single_density': not self._sden
        }
        return checks

    def validate_track(self, tracknum):
        """
        Validate integrity of a specific track.
        Returns dictionary with track validation results.
        """
        if tracknum >= self._ntracks:
            return None

        track_data = self.read_track(tracknum, raw=True)
        if track_data is None:
            return None

        idam_list = self._parse_idam_list(track_data)
        sectors = self.list_sectors(tracknum)

        validation = {
            'track_number': tracknum,
            'idam_entries': len(idam_list),
            'sectors_found': len(sectors),
            'idam_offsets_valid': all(0 < idam['offset'] < self._tracklen for idam in idam_list),
            'all_sectors_have_headers': all(s['sector_size'] > 0 for s in sectors),
            'sectors': sectors
        }

        return validation

    def get_track_sectors(self, tracknum):
        """
        Get all sector data from a track as dictionary.
        Returns dict mapping sector numbers to sector data.
        """
        sectors_dict = {}
        sectors = self.list_sectors(tracknum)

        for sector_info in sectors:
            sector_num = sector_info['sector']
            sector_data = self.read_sector(tracknum, sector_num)
            if sector_data is not None:
                sectors_dict[sector_num] = sector_data

        return sectors_dict

    def get_file_structure(self):
        """
        Return a complete overview of the DMK file structure.
        Useful for debugging and analysis.
        """
        structure = {
            'header': {
                'offset': 0,
                'size': self.VDISK_HDR,
                'write_protected': self._wp,
                'tracks': self._ntracks,
                'track_length': self._tracklen,
                'density': 'Double' if self._sden else 'Single'
            },
            'tracks': []
        }

        for track_num in range(min(self._ntracks, 10)):  # Limit to first 10 for brevity
            track_offset = self._trackstart + (track_num * self._tracklen)
            structure['tracks'].append({
                'track_number': track_num,
                'file_offset': track_offset,
                'idam_offset': track_offset,
                'data_offset': track_offset + self.IDAM_SIZE,
                'sectors': self.list_sectors(track_num)
            })

        return structure

class Hard_Image(Image):
    Header = namedtuple('Header',
                        'id1 id2 ver chksum blks mb4 media flag1 flag2 flag3 crtr dfmt mm dd yy res1 dparm cyl sec gran dcyl label res2')
    HDRSTR = '<BBBBBBBBBBBBBBB12sBBBBB32s192s'
    HLEN = 256

    @classmethod
    def read_header(cls, f) -> Header:
        return cls.Header._make(struct.unpack(cls.HDRSTR, f.read(cls.HLEN)))

    def __init__(self, f):
        Image.__init__(self, 'Hard', f)
        f.seek(0, 0)
        self._header = Hard_Image.read_header(f)
        Image._setGeometry(self, Geometry(1, self._header.cyl))
        self._sector_size = 256
        self._track_offset = self.HLEN

    def read_sector(self, cylinder, sector):
        '''
        Read a single sector from hard disk image.
        Parameters correspond to CHS (Cylinder-Head-Sector) addressing.
        '''
        if cylinder >= self._header.cyl:
            return None
        if sector > self._header.sec:
            return None

        # Calculate offset: (cylinder * sectors_per_cylinder) + sector
        sectors_per_cylinder = self._header.sec * 1  # heads = 1 for this format
        sector_number = (cylinder * sectors_per_cylinder) + sector
        offset = self._track_offset + (sector_number * self._sector_size)

        self._file.seek(offset, 0)
        return self._file.read(self._sector_size)

    def read_track(self, cylinder):
        '''
        Read all sectors from a track (cylinder).
        '''
        track_data = bytearray()
        for sector in range(self._header.sec):
            sector_data = self.read_sector(cylinder, 0, sector)
            if sector_data is None:
                return None
            track_data.extend(sector_data)

        return bytes(track_data)

    def get_geometry(self):
        '''
        Return detailed geometry information from header.
        '''
        return {
            'cylinders': self._header.cyl,
            'sectors_per_track': self._header.sec,
            'sector_size': self._sector_size,
            'block_size': self._header.blks if self._header.blks > 0 else 0x4000,
            'media_type': self._header.media,
            'granule_size': self._header.gran
        }

    def validate_header(self):
        '''
        Validate the hard disk image header.
        '''
        checks = {
            'magic_valid': self._header.id1 == 0x56 and self._header.id2 == 0xcb,
            'has_cylinders': self._header.cyl > 0,
            'has_sectors': self._header.sec > 0,
            'version_ok': self._header.ver <= 3,
            'reasonable_cylinders': self._header.cyl <= 2048,
            'reasonable_sectors': self._header.sec <= 256
        }
        return checks

def create_image(fname):

    fmt = determine_format(fname)
    f = open(fname, 'rb')

    if fmt == JV1:
        return JV1_Image(f)
    elif fmt == JV3:
        return JV3_Image(f)
    elif fmt == DMK:
        return DMK_Image(f)
    elif fmt == HARD:
        return Hard_Image(f)
    else:
        return None
