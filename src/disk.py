#!/usr/bin/python3

from collections import namedtuple
import logging
import string
import struct
import sys

logger = logging.getLogger(__name__)

class OS_Disk(object):

    Config = namedtuple('Config', ['cyls',
                                   'system',
                                   'dd',
                                   'spc',
                                   'sides',
                                   'granules'])

    def __init__(self, image, verbose):
        self._image = image
        self.verbose = verbose
        self._version = None

    def set_type(self, tp: str):
        self.type = tp

    def version(self):
        return self._version

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, value):
        self._config = value

    def sanityCheck(self):
        '''
        Compare values set from reading OS config from the image to
        what the image itself thinks
        '''
        if self._config.sides != self._image.sides:
            print("Num sides mismatch: {} vs {}".format(self._config.sides, self._image.sides))
            sys.exit(-2)

    def configAsString(self):
        retval = list()
        if self._config.system is True:
            retval.append("System")
        else:
            retval.append("Data")

        if self._config.dd is True:
            retval.append("DD")
        else:
            retval.append("SD")

        retval.append("{}-sided".format(self._config.sides))

        retval.append("Cylinders {}".format(self._config.cyls))
        retval.append("Granules {}".format(self._config.granules))
        return retval


class LSDOS_Disk(OS_Disk):
    '''
    Covers LDOS and LSDOS formats. An LDOS disk could be for the Model I
    or Model III.  LSDOS is only Model 4.

    Information from "Programmers Guide to LDOS 6"
    '''

    class Direntry(object):
        """
        The decoded information for a file as stored in a directory entry(s)
        """

        entry_len = 32

        protectionSet = ('FULL', 'REMOVE', 'RENAME', 'WRITE', 'UPDATE', 'READ',
                      'EXEC', 'NO ACCESS')

        # Decoded attributes
        IN_USE = 0
        FPDE = 1
        FXDE = 2

        @classmethod
        def _unpack_entry(cls, entry):
            """
            Break the raw directory entry into a tuple of values.
            """

            return struct.unpack('BBBBB8s3sHHH',
                                 entry[:22]) + struct.unpack('>HHHHBB', entry[22:])

        @classmethod
        def _entry_attrs(cls, attrs):
            retval = set()
            if (attrs & 0x10) != 0:
                retval.add(cls.IN_USE)
                retval.add(cls.FPDE) if (attrs & 0x80) == 0 else \
                    retval.add(cls.FXDE)
                if cls.FXDE in retval:
                    logger.debug("FXDE in use")

            return retval

        def __init__(self, entry):
            """
            Decode the provided directory entry
            """

            (attr,
             flags,
             d2,
             self.eof_off,
             self.lrl,
             self.name,
             self.ext,
             self.OP,
             self.UP,
             self.ERN,
             self.e1,
             self.e2,
             self.e3,
             self.e4,
             self.ff,
             self.fp) = self._unpack_entry(entry)
            logger.debug("0x{:x}".format(self.e1))
            self.attr: int = self._entry_attrs(attr)
            self.protection: int = attr & 0x3
            self.name: str = self.name.decode('ISO-8859-1')
            self.ext: str = self.ext.decode('ISO-8859-1')
            logger.debug("EOF offset is {}, LRL is {}, ERN is {}".format(\
                self.eof_off,
                256 if self.lrl == 0 else self.lrl,
                self.ERN))
            logger.debug("FF 0x{:x}, FE 0x{:x}".format(\
                self. ff,
                self.fp))
    class File(object):
        """
        An access class for a file stored on an LSDOS disk image.
        """

        class Extent(object):
            def __init__(self, raw: int):
                self.cylinder = (raw & 0xff00) >> 8
                self.start_gran = (raw & 0xe0) >> 5
                self.granules = (raw & 0x1f) + 1

        def rel_sector(self, sn, extent):
            """
            For a given sector number (sn) referenced to an extent,work
            out what the actual track and sector.

            An extent only mentions the _starting_ cylinder and granule
            (in the cylinder), along with the number of contiguous
            sectors.  As such the sectors can run off into the next
            cylinder.  So the check is to first determine if the
            current sector goes beyond the starting granule.  if it
            does, then work out what granule it is in, and whether that
            goes beyond the starting cylinder.  With that the
            starting cylinder and relative sector get converted
            to actual cylinder and sector on that cylinder.

            """
            sectorsPerGranule = int(self._cfg.spc / self._cfg.granules)
            cylinder = extent.cylinder
            gran = extent.start_gran + int(sn / sectorsPerGranule)
            if gran >= cylinder:
                logger.debug("Gran overrun")
                increment = int(gran / self._cfg.granules)
                cylinder += increment
                gran -= (increment * self._cfg.granules)
                sn -= (increment * self._cfg.granules * sectorsPerGranule)

            sector = int((gran * sectorsPerGranule) + (sn % sectorsPerGranule))
            return cylinder, sector

        def __init__(self, entries, img, cfg, verbose):
            """
            Create the equvalent of a File Control Block.  The file is left
            in the disk image until read/write operations are carried out.

            endtires is a list containing the FPDE for the file, along with
            any FXDEs.
            """

            self._entries = entries
            self._fpde = entries[0]
            self._img = img
            self._cfg = cfg
            self.verbose = verbose
            logger.debug("LRL {} ERN {}".format(self._fpde.lrl, self._fpde.ERN))

        def records(self):
            return self._fpde.ERN

        def _get_sector(self, sn):
            """
            Locate the exact sector on the disk for file sector number sn.
            Read that from the image and return the contents.
            """

            spg = int(self._cfg.spc / self._cfg.granules)

            reached = 0

            # Note about extents: There is no way to confirm if an extent
            # field has valid data; if the record information for the file
            # specifies a sector that was not covered by previous extents,
            # then this one must have data.
            for entry in self._entries:
                 for ex_r in (entry.e1, entry.e2, entry.e3, entry.e4):
                     logger.debug("extent 0x{:x}".format(ex_r))
                     extent = LSDOS_Disk.File.Extent(ex_r)
                     while True:
                         logger.debug("Grans {} reached {} spg {} sn {}".format(extent.granules, reached, spg, sn))
#                         if (reached + (extent.granules * spg)) > sn: # in here
                         if (reached + spg) > sn: # in here
                             return self._img.read_sector(*self.rel_sector(sn, extent))
                         else:
                             #reached += extent.granules * spg
                             reached += spg

            # If we get here, something went wrong and we can't find
            # the sector.
            raise Exception("Bad entries")

        def read(self, rn):
            """
            Read record  number #rn (starting at 0)
            """

            if (rn > self._fpde.ERN):
                logger.error("Record {} out of range", rn)
                exit(-1)

            # Note: if the lrl _is_ 256 the logic before collapses to
            # sector == rn, offset == 0.
            lrl = 256 if self._fpde.lrl == 0 else self._fpde.lrl
            abs_offset = int(rn * lrl)
            sector = int(abs_offset / 256)
            offset = int(abs_offset - (sector * 256))
            logger.debug("read: record {} is at sector {} offset {}".format(rn, sector, offset))
            #deal with offset later
            return self._get_sector(sector)

    def __init__(self, image, verbose):
        """
        Set up the basic configuration for the supplied image.
        Currently assuming a 5&1/4 inch disk to make track+sector
        information easy.
        """

        OS_Disk.__init__(self, image, verbose)

        s0 = self._image.read_sector(0, 0)
        (b1, b2, b3) = struct.unpack('BBB253x', s0)
        logger.info("Directory on track {}".format(b3))
        self._dir_track = b3
        ds0 = self._image.read_sector(self._dir_track, 0)
        (self._version, cyls, self._cfg) = \
                struct.unpack('BBB', ds0[0xcb:0xce])
        logger.debug("version {} cyls {} cfg 0x{:x}".format(self._version, cyls, self._cfg))
        self._version = (self._version / 0x10, self._version % 0x10)
        if self._version[0] == 6:
            self.set_type('LSDOS')
        else:
            self.set_type('LDOS')
        sides = 2 if (self._cfg & 0x20) else 1
        granules = self._cfg & 0x03 + 1
        self.config = \
                self.Config(cyls=cyls+35,
                            system=(True if (self._cfg & 0x80) else False),
                            dd=(True if (self._cfg & 0x40) else False),
                            spc=(18 if (self._cfg & 0x40) else 10)*sides,
                            sides=sides,
                            granules=((self._cfg & 0x03) + 1))

    @classmethod
    def hash(cls, name: str):
        """
        Hash on a filename 8+3, left-aligned and padded with spaces
        as necessary.

        Logic taken from Sys2.asm in LSDOS source.  Cross-checked against
        logic in SYS2 for TRSDOS2.3 (functionally equivalent)
        """

        res = 0
        for char in name:
            res ^= ord(char)
            # Next two lines achieve Z80 RLCA instruction
            c = (res & 0x80) >> 7
            res = ((res << 1) & 0xff) | c

        if res == 0:
            res += 1

        return res


    def dir_entry_by_hit(self, hit_slot):
        """
        Given a Hash Index Table slot, return the directory entry at the
        corresponding location.
        """

        sn = (hit_slot & 0x1f) + 2
        sector = self._image.read_sector(self._dir_track, sn)
        offset = hit_slot & 0xe0
        f = self.Direntry(sector[offset:offset + self.Direntry.entry_len])
        return f

    def open(self, filename, ext, create=False):
        """
        Return a file object for the specified filename + ext.
        If the file does not exist in the directory the behavior depends
        on the value of create - if False return None, if True create
        a new directory entry and return a new file object (with empty
        file)

        For an exiting file, pull any FXDE entries now and store them in
        the file object.
        """

        aligned_name = filename + ((8 - len(filename)) * ' ') + ext + ((3 - len(ext)) * ' ')
        hash = self.hash(aligned_name)
        HIT = self._image.read_sector(self._dir_track, 1)

        # Given we need to know the exact value where the file is found,
        # use range rather than array slices.
        for i in range(len(HIT)):
            if HIT[i] == hash:
                f = self.dir_entry_by_hit(i)
                if (f.name + f.ext) == aligned_name:
                    entries = list()
                    # Only count an FPDE
                    if f.FPDE in f.attr:
                        entries.append(f)
                        # Extract any FXDEs.
                        ff = f.ff
                        fp = f.fp
                        if ff == 0xfe:
                            logger.debug("Finding FXDEs")
                        while (ff == 0xfe):
                            fx = self.dir_entry_by_hit(fp)
                            assert(fx.name + fx.ext == aligned_name)
                            entries.append(fx)
                            ff = fx.ff
                            fp = fx.fp

                        return self.File(entries,
                                         self._image,
                                         self._config,
                                         self.verbose)
        return None


    def dir(self):
        """
        Read the directory and return as an array of names and metadata
        """

        # In final form, open DIR/SYS and read from there, for now
        # Read directly from sectors.

        retval = list()
        for sector in range(1, self._config.spc):
            sec_dat = self._image.read_sector(self._dir_track, sector)
            num_entries = int(len(sec_dat) / self.Direntry.entry_len)
            for entry in range(num_entries):
                offset = entry * self.Direntry.entry_len
                f = self.Direntry(sec_dat[offset:offset +
                                          self.Direntry.entry_len])
                if self.Direntry.FPDE in f.attr:
                    print(f.name)
                    if f.name.find(' ') != -1:
                        name = f.name[:f.name.find(' ')]
                    else:
                        name = f.name
                    retval.append(('{}/{}'.format(name, f.ext),
                                   LSDOS_Disk.Direntry.protectionSet[f.protection]))

        return retval


class TRSDOS23_Disk(OS_Disk):
    '''
    Covers Model I 2.0-2.3 images

    Information from "TRSDOS 2.3 Decoded and Other Mysteries"
    '''
    def __init__(self, image, verbose):
        OS_Disk.__init__(self, image, verbose)
        self.set_type('TRSDOS2.3')

class TRSDOS13_Disk(OS_Disk):
    '''
    Despite the lower number, TRSDOS 1.3 is for the Model III.

    Information from
    https://www.trs-80.com/sub-reference-dos-trsdos-13-internals.htm
    '''
    def __init__(self, image, verbose):
        OS_Disk.__init__(self, image, verbose)
        self.set_type('TRSDOS1.3')
