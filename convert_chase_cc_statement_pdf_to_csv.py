#! /usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
# Copyright (c) 2012-6 Bryce Adelstein Lelbach aka wash <brycelelbach@gmail.com>
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
###############################################################################

# TODO: Add support for '-' input, e.g. input from stdin.

from sys import exit

from optparse import OptionParser

from os.path import splitext

from subprocess import Popen, PIPE

op = OptionParser(
    usage=(
       "%prog [options] <input-pdf>\n"
"       %prog [options] <input-pdf> <output-csv>\n"
"\n"
"Extracts transaction data from a Chase credit card statement PDF and writes the\n"
"data to a CSV file.\n"
"\n"
"The first argument (<input-pdf>) should be the Chase credit card statement PDF\n"
"file. The output CSV will be written to <output-csv> if it is provided. If\n"
"<output-csv> is '-', the CSV is written to stdout. If <output-csv> is omitted,\n"
"the output is written to a '.csv' file with the same prefix as <input-pdf>"
    )
)

(options, args) = op.parse_args()

if len(args) in range(1, 2)
  op.print_help()
  exit(1)

class io_manager:
  input_pdf  = None
  output_csv = None

  input_data = None

  def __init__(self, input_pdf, output_csv = splitext(input_pdf)[0] + '.csv'):
    self.input_pdf  = open(input_pdf, 'r')
    self.output_pdf = open(output_pdf, 'w')

    # Launch a subprocess that extracts the text from the PDF.
    pdftotext = Popen(["pdftotext", "-raw", input_pdf, "-"], stdout = PIPE)

    # Split the input into an array of lines.
    self.input_data = pdftotext.communicate()[0].split('\n')

    # Reverse the array of lines because we'll be popping lines from the array
    # starting with the first, and removing from the end is more efficient -
    # O(1) vs O(N) (I don't actually know if python lists are implemented as
    # dynamic arrays, but I assume so).
    self.input_data.reverse()

  def __iter__(self):
    return self

  def next(self):
    if len(input_data) == 0:
      raise StopIteration()

    return self.input_data.pop()

im = io_manager(*args)

for line in im:
  print line


