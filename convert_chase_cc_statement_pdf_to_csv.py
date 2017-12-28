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

from re import compile as regex_compile

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

  # Lookahead at the (n + 1)th line. 
  def __getitem__(self, n):
    if len(self.input_pdf_data) <= n:
      # We don't want to terminate on a peek.
      return ''

    return self.input_pdf_data[-(n + 1)]

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
#   meta_data ::= statement_period
#
#   statement_period ::= "Opening/Closing Date " month_day_year " - " month_day_year "\n"
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
#   positive_amount ::= ([0-9]{1,3} (thousands_separator [0-9]{3})*)? decimal_separator [0-9]*
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
#  0.) We start in the "summary" state.
#  1.) We scan for meta data.
#  2.) When we find the meta data, we enter the "meta data" state.
#  3.) We parse meta data.
#  4.) We enter the "non-transaction" state.
#  5.) We scan for transaction headers.
#  6.) When we find the 1st transaction header, we enter the "transaction" state.
#  7.) We parse transaction records.
#  8.) When we we encounter a line that does not match as a transaction record,
#      we enter the "non-transaction" state.
#  9.) We scan for transaction headers.
# 10.) When we find the next transaction header, we enter the "transaction state".
# 11.) Go to step 7.
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

###############################################################################

class parser:
  SUMMARY_STATE         = 0
  META_DATA_STATE       = 1
  TRANSACTION_STATE     = 2
  NON_TRANSACTION_STATE = 3

  state = None

  iom = None

  def __init__(self, iom):
    self.state = self.SUMMARY_STATE
    self.iom   = iom

  def parse_summary(self):
    # Scan for meta data (lookahead).
    if self.iom[0].startswith("Opening/Closing Date "):
      self.state = self.META_DATA_STATE
    else:
      # Only consume the line if it's not the start of the meta data.
      self.iom.next()

  def parse_meta_data(self):
    # FIXME: Make this a class.

    line = self.iom.next()

    two_digits_rule       = r'[0-9]{2}'

    month_day_year_rule   = r'(' + two_digits_rule + r')/' \
                          + r'(' + two_digits_rule + r')/' \
                          + r'(' + two_digits_rule + r')'

    statement_period_rule = r'Opening/Closing Date '  \
                          + month_day_year_rule       \
                          + r' - '                    \
                          + month_day_year_rule       \
                          + r'$'

    engine = regex_compile(statement_period_rule)                          
   
    match = engine.match(line)

    assert match != None

    print "PARSED OPENING MONTH:", match.group(1)
    print "PARSED OPENING DAY:  ", match.group(2)
    print "PARSED OPENING YEAR: ", match.group(3)
    print "PARSED CLOSING MONTH:", match.group(4)
    print "PARSED CLOSING DAY:  ", match.group(5)
    print "PARSED CLOSING YEAR: ", match.group(6)

    self.state = self.NON_TRANSACTION_STATE

  def parse_non_transaction(self):
    line = self.iom.next()

    # Scan for transaction headers.
    h1 = "Date of" 
    h2 = "Transaction Merchant Name or Transaction Description $ Amount"
    if line == h1 and self.iom[0] == h2: # Lookahead.
      # Consume the rest of the header.
      self.iom.next()

      self.state = self.TRANSACTION_STATE

  def parse_transaction(self):
    # FIXME: Make this a class.

    # TODO: Foreign

    line = self.iom.next()

    two_digits_rule = r'[0-9]{2}'

    month_day_rule  = r'(' + two_digits_rule + r')/(' + two_digits_rule + r')'

    decimal_separator_rule   = r'.' # TODO: Localization.
    thousands_separator_rule = r',' # TODO: Localization.

    positive_amount_rule = r'[0-9]{1,3}(?:' + thousands_separator_rule + r'[0-9]{3})*' + decimal_separator_rule + '[0-9]*'

    transaction_amount_rule = r'(-?' + positive_amount_rule + r')'

    transaction_description_rule = r'(.*)'

    domestic_transaction_record_rule = month_day_rule + r' ' + transaction_description_rule + r' ' + transaction_amount_rule + r'$'

    engine = regex_compile(domestic_transaction_record_rule)                          
   
    match = engine.match(line)

    if match == None:
      # We've reached the end of this transaction data block
      self.state = self.NON_TRANSACTION_STATE
    else:
      print "PARSED TRANSACTION MONTH:      ", match.group(1)
      print "PARSED TRANSACTION DAY:        ", match.group(2)
      print "PARSED TRANSACTION DESCRIPTION:", match.group(3)
      print "PARSED TRANSACTION AMOUNT:     ", match.group(4)

  def parse(self):
    while True:
      print "STATE:", self.state
      if   self.state == self.SUMMARY_STATE:
        self.parse_summary()
      elif self.state == self.META_DATA_STATE:
        self.parse_meta_data()
      elif self.state == self.TRANSACTION_STATE:
        self.parse_transaction()
      elif self.state == self.NON_TRANSACTION_STATE:
        self.parse_non_transaction()
      else:
        assert false, "Parser state is invalid" 

###############################################################################

(options, args) = parse_command_line()

# Read input file into an array of lines and open the output file.
iom = io_manager(*args)

# Compile parser.
p = parser(iom)

# Parse array of lines and print transactions as we go.
p.parse()

# TESTING: Write pdftotext -raw output. 
#for line in iom:
#  print >> iom, line


