#! /usr/bin/env python
#encoding:UTF-8

# Copyright (c) 2012 Victor Terron. All rights reserved.
# Institute of Astrophysics of Andalusia, IAA-CSIC
#
# This file is part of LEMON.
#
# LEMON is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import division

import logging
import optparse
import os
import shutil
import subprocess
import sys
import tempfile
import warnings

# LEMON modules
import customparser
import defaults
import fitsimage
import keywords
import methods
import style

description = """
This module uses a local build of the Astrometry.net software in order to
compute the astrometric solution of the input FITS files, saving the new files,
containing the WCS header, to the output directory. This is, in essence, a mere
simple interface to solve-field, Astrometry.net's command-line high-level user
interface, which must be present in PATH. Keep in mind that for Astrometry.net
to work it is also necessary to download the index files.

"""

ASTROMETRY_COMMAND = 'solve-field'

class AstrometryNetNotInstalled(StandardError):
    """ Raised if Astrometry.net is not installed on the system """
    pass

class AstrometryNetError(subprocess.CalledProcessError):
    """ Raised if the execution of Astrometry.net fails """
    pass

class AstrometryNetUnsolvedField(subprocess.CalledProcessError):
    """ Raised if Astrometry.net could not solve the field """

    def __init__(self, path):
        self.path = path

    def __str__(self):
        return "%s: could not solve field" % self.path

def astrometry_net(path, ra = None, dec = None, radius = 1, verbosity = 0):
    """ Do astrometry on a FITS image using Astrometry.net.

    Use a local build of the amazing Astrometry.net software [1] in order to
    compute the astrometric solution of a FITS image. This software has many,
    many advantages over the well-respected SCAMP, but the most important one
    is that it is a blind astrometric calibration service. We do not need to
    know literally anything about the image, including approximate coordinates,
    scale and equinox. It just works, giving us a new FITS file containing the
    WCS header.

    In order for this function to work, you must have built and installed the
    Astrometry.net code in your machine [2]. The main high-level command-line
    user interface, 'solve-field', is expected to be available in your PATH;
    otherwise, the AstrometryNetNotInstalled exception is raised. Note that you
    also need to download the appropriate index files, which are considerably
    heavy. At the time of this writing, the entire set of indexes built from
    the 2MASS catalog [4] has a total size of ~32 gigabytes.

    Raises AstrometryNetError if Astrometry.net exits with a non-zero status
    code, and AstrometryNetUnsolvedField if an astrometric solution cannot be
    found. The latter usually happens because Astrometry.net has to stop at
    some point: as long as a reasonable number of stars are detected, there are
    gazillions of possible matches between the image and the sky to check, so
    it gives up when the CPU time limit is hit [5]. This limit can be set in
    the backend.cfg file, by default located in /usr/local/astrometry/etc/.

    [1] http://astrometry.net/
    [2] http://astrometry.net/doc/build.html
    [3] http://astrometry.net/doc/readme.html#getting-index-files
    [4] http://data.astrometry.net/4200/
    [5] https://groups.google.com/d/msg/astrometry/ORVkOk0jSZg/PeCMeAJodyAJ

    Keyword arguments:

    ra,
    dec,
    radius - restrict the Astrometry.net search to those indexes within
             'radius' degrees of the field center given by ('ra', 'dec').
             Both the right ascension and declination must be given in order
             for this feature to work. The three arguments must be expressed
             in degrees.

    verbosity - the verbosity level. The higher this value, the 'chattier'
                Astrometry.net will be. Most of the time, a verbosity other
                than zero, the default value, is only needed for debugging.

    """

    emsg = "'%s' not found in the current environment"
    if not methods.which(ASTROMETRY_COMMAND):
        raise AstrometryNetNotInstalled(emsg % ASTROMETRY_COMMAND)

    img = fitsimage.FITSImage(path)
    tempfile_prefix = '%s_' % img.basename_woe
    # Place all output files in this directory
    kwargs = dict(prefix = tempfile_prefix, suffix = '_astrometry.net')
    output_dir = tempfile.mkdtemp(**kwargs)

    # Path to the temporary FITS file containing the WCS header
    root, ext = os.path.splitext(img.basename)
    kwargs = dict(prefix = '%s_astrometry_' % root, suffix = ext)
    with tempfile.NamedTemporaryFile(**kwargs) as fd:
        output_path = fd.name

    # If the field solved, Astrometry.net creates a <base>.solved output file
    # that contains (binary) 1. That is: if this file does not exist, we know
    # that an astrometric solution could not be found.
    solved_file = os.path.join(output_dir, root + '.solved')

    # --dir: place all output files in the specified directory.
    # --no-plots: don't create any plots of the results.
    # --new-fits: the new FITS file containing the WCS header.
    # --no-fits2fits: don't sanitize FITS files; assume they're already valid.
    # --overwrite: overwrite output files if they already exist.

    args = [ASTROMETRY_COMMAND, path,
            '--dir', output_dir,
            '--no-plots',
            '--new-fits', output_path,
            '--no-fits2fits',
            '--overwrite']

    # -3 / --ra <degrees or hh:mm:ss>: only search in indexes within 'radius'
    # of the field center given by 'ra' and 'dec'
    # -4 / --dec <degrees or [+-]dd:mm:ss>: only search in indexes within
    # 'radius' of the field center given by 'ra' and 'dec'
    # -5 / --radius <degrees>: only search in indexes within 'radius' of the
    # field center given by ('ra', 'dec')

    if ra is not None:
        args += ['--ra', '%f' % ra]

    if dec is not None:
        args += ['--dec', '%f' % dec]

    if radius is not None:
        args += ['--radius', '%f' % radius]

    # -v / --verbose: be more chatty -- repeat for even more verboseness
    if verbosity:
        args.append('-%s' % ('v' * verbosity))

    try:
        subprocess.check_call(args)

        # .solved file must exist and contain a binary one
        with open(solved_file, 'rb') as fd:
            if ord(fd.read()) != 1:
                raise AstrometryNetUnsolvedField(path)

        return output_path

    except subprocess.CalledProcessError, e:
        raise AstrometryNetError(e.returncode, e.cmd)
    # If .solved file doesn't exist or contain one
    except (IOError, AstrometryNetUnsolvedField):
        raise AstrometryNetUnsolvedField(path)
    finally:
        shutil.rmtree(output_dir, ignore_errors = True)


parser = customparser.get_parser(description)
parser.usage = "%prog [OPTION]... INPUT_IMGS... OUTPUT_DIR"

parser.add_option('--radius', action = 'store', type = 'float',
                  dest = 'radius', default = 1,
                  help = "only search in indexes within this number of "
                  "degrees of the field center, whose coordinates are read "
                  "from the FITS header of each image (keywords --rak and "
                  "--deck). [default: %default]")

parser.add_option('--blind', action = 'store_true', dest = 'blind',
                  help = "ignore --radius, --rak and --deck and solve the "
                  "images blindly. A necessity in case the FITS headers of "
                  "your data have no information about the telescope "
                  "pointing, or when they do but it is deemed to be "
                  "entirely unreliable")

parser.add_option('--suffix', action = 'store', type = 'str',
                  dest = 'suffix', default = 'a',
                  help = "string to be appended to output images, before "
                  "the file extension, of course [default: %default]")

parser.add_option('-v', '--verbose', action = 'count',
                  dest = 'verbose', default = defaults.verbosity,
                  help = defaults.desc['verbosity'] + " The verbosity "
                  "level is also passed down to Astrometry.net, causing "
                  "it to be increasingly chattier as more -v flags are "
                  "given")

key_group = optparse.OptionGroup(parser, "FITS Keywords",
                                 keywords.group_description)

key_group.add_option('--rak', action = 'store', type = 'str',
                     dest = 'rak', default = keywords.rak,
                     help = keywords.desc['rak'])

key_group.add_option('--deck', action = 'store', type = 'str',
                     dest = 'deck', default = keywords.deck,
                     help = keywords.desc['deck'])

parser.add_option_group(key_group)
customparser.clear_metavars(parser)

def main(arguments = None):
    """ main() function, encapsulated in a method to allow for easy invokation.

    This method follows Guido van Rossum's suggestions on how to write Python
    main() functions in order to make them more flexible. By encapsulating the
    main code of the script in a function and making it take an optional
    argument the script can be called not only from other modules, but also
    from the interactive Python prompt.

    Guido van van Rossum - Python main() functions:
    http://www.artima.com/weblogs/viewpost.jsp?thread=4829

    Keyword arguments:
    arguments - the list of command line arguments passed to the script.

    """

    if arguments is None:
        arguments = sys.argv[1:] # ignore argv[0], the script name
    (options, args) = parser.parse_args(args = arguments)

    # Adjust the logger level to WARNING, INFO or DEBUG, depending on the
    # given number of -v options (none, one or two or more, respectively)
    logging_level = logging.WARNING
    if options.verbose == 1:
        logging_level = logging.INFO
    elif options.verbose >= 2:
        logging_level = logging.DEBUG
    logging.basicConfig(format = style.LOG_FORMAT, level = logging_level)

    # Print the help and abort the execution if there are not two positional
    # arguments left after parsing the options, as the user must specify at
    # least one (only one?) input FITS file and the output directory
    if len(args) < 2:
        parser.print_help()
        return 2     # 2 is generally used for command line syntax errors
    else:
        input_paths = args[:-1]
        output_dir = args[-1]

    # No index can be within the search area if the radius is not > 0
    if options.radius <= 0:
        msg = "%sError: --radius must a positive number of degrees"
        print msg % style.prefix
        sys.exit(style.error_exit_message)

    # Make sure that the output directory exists; create it if it doesn't.
    methods.determine_output_dir(output_dir)

    msg = "%s%d paths given as input, on which astrometry will be done."
    print msg % (style.prefix, len(input_paths))
    print "%sUsing a local build of Astrometry.net." % style.prefix
    msg = "%sLines not starting with '%s' come from Astrometry.net."
    print msg % (style.prefix, style.prefix.strip())
    print

    for path in input_paths:
        img = fitsimage.FITSImage(path)
        # Add the suffix to the basename of the FITS image
        root, ext = os.path.splitext(os.path.basename(path))
        output_filename = root + options.suffix + ext
        dest_path = os.path.join(output_dir, output_filename)

        try:
            msg = "%s: reading α from FITS header (keyword '%s')"
            logging.debug(msg % (img.path, options.rak))
            ra  = float(img.read_keyword(options.rak))
            msg = "%s: α = %.5f" % (img.path, ra)
            logging.debug(msg)

            msg = "%s: reading δ from FITS header (keyword '%s')"
            logging.debug(msg % (img.path, options.deck))
            dec = float(img.read_keyword(options.deck))
            msg = "%s: δ = %.5f" % (img.path, dec)
            logging.debug(msg)

            msg = "%s: radius = %.2f degrees" % (img.path, options.radius)
            logging.debug(msg)

        except (ValueError, KeyError), e:
            msg = "%s: %s" % (img.path, str(e))
            logging.debug(msg)
            ra = dec = radius = None
            msg = "%s: could not read coordinates from FITS header"
            logging.debug(msg % img.path)
            msg = "%s: using α = δ = radius = None"
            logging.debug(msg % img.path)

        kwargs = dict(ra = ra,
                      dec = dec,
                      radius = options.radius,
                      verbosity = options.verbose)

        try:
            output_path = astrometry_net(img.path, **kwargs)
        except AstrometryNetUnsolvedField:
            msg = "%s did not solve. Ignored." % img.path
            print style.prefix + msg
            warnings.warn(msg, RuntimeWarning)
            continue

        try:
            shutil.move(output_path, dest_path)
        except (IOError, OSError):
            try: os.unlink(output_path)
            except (IOError, OSError): pass

        output_img = fitsimage.FITSImage(dest_path)

        msg1 = "Astrometry done via LEMON on %s" % methods.utctime()
        msg2 = "[Astrometry] WCS solution found by Astrometry.net"
        msg3 = "[Astrometry] Original image: %s" % img.path

        output_img.add_history(msg1)
        output_img.add_history(msg2)
        output_img.add_history(msg3)

        msg = "%s%s solved and saved to %s"
        print  msg % (style.prefix, img.path, output_img.path)

    print "%sYou're done ^_^" % style.prefix
    return 0

if __name__ == "__main__":
    sys.exit(main())

