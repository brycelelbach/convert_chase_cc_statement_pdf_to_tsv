#! /usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
# Copyright (c) 2012-6 Bryce Adelstein Lelbach aka wash <brycelelbach@gmail.com>
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
###############################################################################

# TODO: Add support for '-' input, e.g. input from stdin.

from sys import exit, stdout

from optparse import OptionParser

from os.path import splitext

from subprocess import Popen, PIPE

op = OptionParser(
    usage=(
       "%prog [options] <input-pdf>\n"
"       %prog [options] <input-pdf> <output-csv>\n"
"\n"
"Extracts transaction data from a Chase credit card statement PDF and writes it\n"
"to a CSV file.\n"
"\n"
"The first argument (<input-pdf>) specifies the Chase credit card statement PDF\n"
"file to read. The output CSV will be written to <output-csv> if it is provided.\n"
"If <output-csv> is '-', the CSV is written to stdout. If <output-csv> is omitted,\n"
"the output is written to a '.csv' file with the same prefix as <input-pdf>"
    )
)

(options, args) = op.parse_args()

if len(args) not in range(1, 3):
  op.print_help()
  exit(1)

class io_manager:
  output_csv_file = None # File object that the output CSV is written to.
  input_pdf_data  = None # Array of newline-terminated strings from the PDF.

  def __init__(self, input_pdf_name, output_csv_name = None):
    if   output_csv_name == "-":  # Output to stdout.
      self.output_csv_file = stdout
    elif output_csv_name == None: # Output to file: input prefix + '.csv'.
      self.output_csv_file = open(splitext(input_pdf_name)[0] + ".csv", "w")
    else:                         # Output to file: user-specified.
      self.output_csv_file = open(output_csv_name, "w")

    # Launch a subprocess that extracts the text from the input PDF.
    pdftotext = Popen(["pdftotext", "-raw", input_pdf_name, "-"], stdout = PIPE)

    # Split the input into an array of lines.
    self.input_pdf_data = pdftotext.communicate()[0].split("\n")

    # Reverse the array of lines because we'll be popping lines from the array
    # starting with the first, and removing from the end is more efficient -
    # O(1) vs O(N) (I don't actually know if python lists are implemented as
    # dynamic arrays, but I assume so).
    self.input_pdf_data.reverse()

  # Iterable requirement.
  def __iter__(self):
    return self

  # Iterator requirement.
  def next(self):
    if len(self.input_pdf_data) == 0:
      raise StopIteration()

    return self.input_pdf_data.pop()

  # Printable requirement.
  def write(self, str):
    self.output_csv_file.write(str)

im = io_manager(*args)

for line in im:
  print >> im, line


