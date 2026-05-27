# dmk-util
Python Utility for manipulating some TRS-80 disk images

This supports the reading and (eventually) modificaion of the following 
image formats:

 - JV1
 - JV3
 - DMK
 - Reed "Hard Disk"
 
 LDOS/LSDOS disk images are currently supported.  TRSDOS 2.3 and 1.3 (Model
 III) will be supported "soon"
 
 `./dmk-util.py -h` for full details
 
 # Why?
 There are lots of existing utilities which can handle this stuff, as 
 shown by a quick read of
 
 https://www.trs-80.com/main-emulation-disk-utilities.htm
 
 and that doesn't cover the utilities that come with xtrs or sdltrs.
 
 So why write "yet another" tool?  There are several reasons, the simplest
 are:
 
  - A lot of the utilites are DOS / Windows only
  - I don't see a comprehensive documentation of the formats independent
    of implementation. I am trying to add this in the files here so
    I (or anyone else who cares) gets a comprehensive description.
  - I feel like it :-)  And it's a learning experience.
  
As of writing this the functionality is pretty limited, but expanding.
Right now you can:

 - Get information on the image format
 - Get minimal information about the LDOS/LSDOS setup
 - Read the directory
 - Extract individual files
 
 . . . and that's it.  And that is only about 90% perfect.  But it's a start
 
 
