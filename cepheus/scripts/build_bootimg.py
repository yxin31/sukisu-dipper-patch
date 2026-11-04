#!/usr/bin/env python3
"""Rebuild Xiaomi Mi 9 (cepheus) boot.img with a freshly built kernel Image.

MIUI 12.5 boot.img for cepheus is an Android header v1 image whose kernel
section is a "UNCOMPRESSED_IMG" container:

    16B  b"UNCOMPRESSED_IMG"
     4B  little-endian u32 = length of the raw arm64 Image that follows
     N   raw arm64 Image  (magic "ARMd" at offset 0x38)
     M   stock device tree blob(s)  (5 concatenated FDTs on this device)

It has no ramdisk (ramdisk_size == 0).  We keep the stock header, the stock
dtb and the stock cmdline byte-for-byte, and only swap the Image in the
middle, so panel / fingerprint / touch configuration stays exactly as the
device shipped with.
"""

import argparse
import os
import struct
import sys

BOOT_MAGIC = b'ANDROID!'
SEG_MAGIC = b'UNCOMPRESSED_IMG'
FDT_MAGIC = b'\xd0\x0d\xfe\xed'


def die(msg):
    sys.stderr.write('ERROR: %s\n' % msg)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--header', required=True, help='stock boot.img header template (4 KiB)')
    ap.add_argument('--image', required=True, help='new raw arm64 Image')
    ap.add_argument('--dtb', required=True, help='stock dtb blob extracted from boot.img')
    ap.add_argument('--out', required=True, help='output boot.img')
    args = ap.parse_args()

    hdr = bytearray(open(args.header, 'rb').read())
    if hdr[:8] != BOOT_MAGIC:
        die('header template is not an ANDROID! boot header')

    page_size = struct.unpack('<I', hdr[36:40])[0]
    if page_size not in (2048, 4096, 8192, 16384):
        die('unexpected page_size %d' % page_size)
    if len(hdr) < page_size:
        hdr = hdr.ljust(page_size, b'\x00')

    image = open(args.image, 'rb').read()
    dtb = open(args.dtb, 'rb').read()

    if len(image) < 0x40:
        die('Image too small (%d bytes)' % len(image))
    if image[0x38:0x3c] != b'ARMd':
        die('not an arm64 Image: magic "ARMd" missing at offset 0x38 '
            '(looks like a compressed Image.gz - build target `Image`, not `Image.gz`)')
    text_offset = struct.unpack('<Q', image[8:16])[0]
    if text_offset != 0x80000:
        sys.exit('WARNING: text_offset is 0x%x, stock is 0x80000' % text_offset)
    if dtb[:4] != FDT_MAGIC:
        die('dtb blob does not start with FDT magic d00dfeed')

    seg = SEG_MAGIC + struct.pack('<I', len(image)) + image + dtb

    # update kernel_size in the stock header
    struct.pack_into('<I', hdr, 8, len(seg))

    out = bytearray(hdr[:page_size])
    out += seg
    out += b'\x00' * ((-len(seg)) % page_size)

    with open(args.out, 'wb') as f:
        f.write(out)

    print('image          : %d bytes' % len(image))
    print('stock dtb      : %d bytes' % len(dtb))
    print('kernel section : %d bytes' % len(seg))
    print('boot.img       : %d bytes (%.2f MB)' % (len(out), len(out) / 1048576.0))
    print('wrote %s' % args.out)


if __name__ == '__main__':
    main()
