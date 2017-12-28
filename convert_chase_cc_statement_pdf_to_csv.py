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

###############################################################################

def parse_command_line():
  op = OptionParser(
    usage=(
             "%prog [options] <input-pdf>\n"
      "       %prog [options] <input-pdf> <output-csv>\n"
      "\n"
      "Extracts transaction data from a Chase credit card statement PDF and writes it\n"
      "to a CSV file.\n"
      "\n"
      "The 1st argument (<input-pdf>) specifies the Chase credit card statement PDF file\n"
      "to read. The output CSV will be written to <output-csv> if it is provided. If\n"
      "<output-csv> is '-', the CSV is written to stdout. If <output-csv> is omitted,\n"
      "the output is written to a '.csv' file with the same prefix as <input-pdf>"
      "\n"
      "NOTE: This program was designed for and tested with Chase Sapphire credit card\n"
      "statements. Some aspects of this program may not work for other Chase credit\n"
      "cards.\n"
    )
  )

  (options, args) = op.parse_args()

  if len(args) not in range(1, 3):
    op.print_help()
    exit(1)

  return (options, args)

###############################################################################

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
    # starting with the 1st, and removing from the end is more efficient - O(1)
    # vs O(N) (I don't actually know if python lists are implemented as dynamic
    # arrays, but I assume so).
    self.input_pdf_data.reverse()

  # Iterable requirement.
  def __iter__(self):
    return self

  # Iterator requirement.
  def next(self):
    if len(self.input_pdf_data) == 0:
      raise StopIteration()

    return self.input_pdf_data.pop()

  # Lookahead at the nth line. 
  def peek(self, n = 1):
    if len(self.input_pdf_data) < n:
      # We don't want to terminate on a peek.
      return ''

    return self.input_pdf_data[-n]

  # Printable requirement.
  def write(self, str):
    self.output_csv_file.write(str)

###############################################################################

###############################################################################
# Grammar for the pdftotext -raw output of a Chase credit card statement PDF.
###############################################################################
#
# This is a Parsing Expression Grammar {1} described in Extended Backus-Naur
# Form (please forgive me - old habits of a Boost.Spirit developer) {2, 3, 4, 5}.
# [chars] denotes a regex style character class. There is no whitespace skip
# parsing.
#
# The file is a sequence of UTF-8 characters that consists of transaction data
# and non-transaction data. Most non-transaction data is uninteresting, but
# there is some useful meta data in the statement summary, which is the
# non-transaction data preceding the 1st transaction data segment.
#
#   file ::= statement_summary (transaction_data | non_transaction_data)*
#
#   non_transaction_data ::= [^\n]* "\n" 
#
# The statement summary consists of non-transaction data, some of which is useful
# meta data. We extract some, but not all, of this meta data. 
#
#   statement_summary ::= (non_transaction_data* meta_data non_transaction_data*) - transaction_header
#
#   meta_data ::= transaction_period
#
#   transaction_period ::= "Opening/Closing Date " month_day_year " - " month_day_year "\n"
#
#   month_day_year ::= two_digits "/" two_digits "/" two_digits
#
#   two_digits ::= [0-9] [0-9]
#
# Transaction data always begins with a header. The header is followed by a
# sequence of transaction records. Transaction data does not have a footer, but
# transaction records always end in newline characters.
#
#   transaction_data ::= transaction_header transaction_record*
#
#   transaction_data_header ::= "Date of\nTransaction Merchant Name or Transaction Description $ Amount\n"
#
# A transaction record has 3 components: month/day date, description, and amount.
# There are 2 types of transaction records: domestic and foreign.
# 
#   transaction_record ::= foreign_transaction_record | domestic_transaction_record
#
#   domestic_transaction_record ::= month_day " " transaction_description " " transaction_amount "\n"
#
#   month_day ::= two_digits "/" two_digits 
# 
#   transaction_description ::= ((([^\n ]+) - (transaction_amount "\n")) % " ")
# 
#   transaction_amount ::= "-"? positive_amount
#
#   positive_amount ::= (([0-9] [0-9]? [0-9]?) % thousands_separator)? decimal_separator [0-9]*
# 
#   decimal_separator is local dependent
#   thousands_separator is local dependent 
#
# Foreign transaction records are an extension of domestic transaction records
# which include exchange rate information. 
#
#   foreign_transaction_record ::= domestic_transaction_record exchange_rate_record
#
#   exchange_rate_record ::= month_day " " exchange_rate_currency "\n" exchange_rate_amount "\n"
#
#   exchange_rate_currency ::= transaction_description
#
#   exchange_rate_amount ::= positive_amount " X " positive_amount " (EXCHG RATE)\n"
#
# {1}: https://ciere.com/cppnow15/x3_docs/spirit/abstracts/parsing_expression_grammar.html
# {2}: https://ciere.com/cppnow15/x3_docs/spirit/introduction.html
# {3}: https://ciere.com/cppnow15/x3_docs/spirit/quick_reference/operator.html
# {4}: https://ciere.com/cppnow15/x3_docs/spirit/quick_reference/directive.html
# {5}: https://ciere.com/cppnow15/x3_docs/spirit/quick_reference/auxiliary.html

# RANDOM NOTES
#
# The file consists of a series of newline character terminated ("\n") UTF-8
# strings ("lines"). Some groups of consecutive lines are transaction data. All
# other lines are non-transaction data. 
#
# Instead of running a full parser on the entire input, we split it up into an
# array of newline character separated lines, scan for the meta data and
# transaction data lines, and then parse those fully. This works quite well;
# most of the multi-line interactions in the parser can be treated as states:
#
# 0.) We start in the "summary" state.
# 1.) We scan for meta data and transaction headers.
# 2.) When we find the 1st transaction header, we enter the "transaction" state.
#     * If we haven't found the necessary meta data when we transition to the
#       "transaction" state, an error is raised.
# 3.) We parse transaction records.
#     * If we run out of input in this state, an error is raised.
# 4.) When we we encounter a line that does not match as a transaction record,
#     we enter the "non-transaction" state.
# 5.) We scan for transaction headers.
#     * If we run out of input in this state, parsing successfully terminates.
# 6.) When we find the next transaction header, we enter the "transaction state".
# 7.) Go to step 3.
# 
# Regrettably, there is one more complicated multi-line interaction. Foreign
# transactions are a superset of the domestic transaction record pattern and
# contain newline characters followed directly by month/day dates (the same
# pattern that domestic transaction records begin with). This requires
# lookahead across multiple lines (2 lines ahead), which is somewhat
# unfortunate.
#
# The last word of the description seems to always be the location where the
# transaction occurred.
#
# It's possible that the exchange rate amounts do not use thousands separators.
# I don't have a large enough foreign transaction in any of my statements to
# determine this. If this is the case, at the least the grammar needs to be
# updated.

class parser:
  SUMMARY_STATE         = 0
  TRANSACTION_STATE     = 1
  NON_TRANSACTION_STATE = 2

  state = None

###############################################################################

(options, args) = parse_command_line()

# Read input file into an array of lines and open the output file.
iom = io_manager(*args)

# Parse array of lines and print transactions as we go.
# TODO

# TESTING: Write pdftotext -raw output. 
#for line in iom:
#  print >> iom, line

# TESTING: Parser state changes and scanning. 


