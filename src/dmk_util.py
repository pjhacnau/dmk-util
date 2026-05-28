#!/usr/bin/env python3

import argparse
import logging

from image import create_image
from disk import LSDOS_Disk

logger = logging.getLogger('dmk-util')

def main():
    parser = argparse.ArgumentParser(description="DSK file processing")
    parser.add_argument('-v', '--verbose', action='store_true')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-i',
                       '--image',
                       action='store_true',
                       help='Work on the Image only')
    group.add_argument('-d',
                       '--directory',
                       action='store_true',
                       help='List directory')
    group.add_argument('-e',
                       '--extract',
                       dest='exfile',
                       metavar='FILE',
                       action='store',
                       help='Extract FILE from the image')
    parser.add_argument('-t',
                        '--track',
                        type=int,
                        default=-1,
                        help='Dump track (only valid with --image)')
    parser.add_argument('file', metavar='IMAGE', help='Disk Image file')

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    image = create_image(args.file)

    logger.info("Format is {}".format(image.format()))

    if args.image is False:
        #right now only one OS supported
        osd = LSDOS_Disk(image, args.verbose)

        osd.sanityCheck()

        logger.info("{} {}.{}".format(osd.type, osd.version()[0], osd.version()[1]))
        logger.info(osd.configAsString())

        if args.directory is True:
            print("FILE\t\tPROT")
            print(22 * "-")
            for (name, prot) in osd.dir():
                print("{:s}\t{:s}".format(name + ' ' * (11 - len(name)),
                                          prot))

        if args.exfile is not None:
            (fname, fext) = args.exfile.split('/')
            fl = osd.open(fname, fext)
            if fl is not None:
                logger.info("Found file {}".format(args.exfile))
                with open('{}.{}'.format(fname, fext), 'wb') as ofl:
                    logger.debug(fl)
                    logger.debug(fl.records())
                    for rn in range(fl.records()):
                        ofl.write(fl.read(rn))
            else:
                print("File {} not found".format(args.exfile))
    else:
        if args.track != -1:
            print("Extract track {}".format(args.track))
            print(image.read_track(args.track, True).hex())

if __name__ == "__main__":
    main()
