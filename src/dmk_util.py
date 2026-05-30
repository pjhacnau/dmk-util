#!/usr/bin/env python3
"""
A utility to manipulate disk images containing data formatted with
a specific TRS-80 Operating System.

   Copyright 2025 Peter Howard <pjh@northern-ridge.com.au>

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

"""

import argparse
import logging

from image import create_image
from disk import LSDOS_Disk

logger = logging.getLogger('dmk-util')

def main():
    parser = argparse.ArgumentParser(description="DSK file processing")
    parser.add_argument('-v', '--verbose',
                        action='count',
                        default=0,
                        help='Show more information; max when specified twice')
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

    if args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG)
    elif args.verbose == 1:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    image = create_image(args.file)

    logger.info("Format is {}".format(image.format()))

    if not args.image:
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
                logger.error("File {} not found".format(args.exfile))
    else:
        if args.track != -1:
            print("Extract track {}".format(args.track))
            print(image.read_track(args.track, True).hex())

if __name__ == "__main__":
    main()
