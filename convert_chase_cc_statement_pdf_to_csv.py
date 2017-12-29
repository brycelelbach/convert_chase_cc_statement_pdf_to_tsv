#! /usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
# Copyright (c) 2012-6 Bryce Adelstein Lelbach aka wash <brycelelbach@gmail.com>
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
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
#   domestic_transaction_record ::= month_day " " transaction_description " " quantity "\n"
#
#   transaction_description ::= ((([^\n ]+) - (quantity "\n")) % " ")
#
#   month_day ::= two_digits "/" two_digits 
# 
#   quantity ::= "-"? positive_quantity
#
#   positive_quantity ::= ([0-9]{1,3} ("," [0-9]{3})*)? "." [0-9]*
#
# Foreign transaction records are an extension of domestic transaction records
# which include exchange rate information. 
#
#   foreign_transaction_record ::= domestic_transaction_record exchange_record
#
#   exchange_record ::= exchange_date_and_currency exchange_rate_calculation
#
#   exchange_date_and_currency ::= month_day " " transaction_description "\n"
#
#   exchange_rate_calculation ::= positive_quantity " X " positive_quantity " (EXCHG RATE)\n"
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
#
# I don't know if numbers in statements are localized differently for non-US
# customers. Currently localization for numbers is not accounted for.

###############################################################################

# TODO: Add support for '-' input, e.g. input from stdin.

from sys import exit, stdout

from os.path import splitext

from subprocess import Popen, PIPE

from optparse import OptionParser

from re import compile as regex_compile

###############################################################################

def crange(start, end): return range(start, end + 1)

def atof(str): return float(str.replace(",", ""))

###############################################################################

# Returns a new class type that has a member with a singleton variable with a
# unique type for each string in `states`.
#
# Loosely inspired by: https://www.pythoncentral.io/how-to-implement-an-enum-in-python
def enum(*states):
  members = dict(map(lambda n: (n, type(n, (), dict(__repr__ = lambda s: n))()), states))
  return type("enum", (), members)

###############################################################################

def parse_command_line():
  op = OptionParser(
    usage=(
             "%prog [options] <input-pdf>\n"
      "       %prog [options] <input-pdf> <output-tsv>\n"
      "\n"
      "Extracts transaction data from a Chase credit card statement PDF and writes it\n"
      "to a tab-separated-values (TSV) file.\n"
      "\n"
      "The 1st argument (<input-pdf>) specifies the Chase credit card statement PDF file\n"
      "to read. The output TSV will be written to <output-tsv> if it is provided. If\n"
      "<output-tsv> is '-', the TSV is written to stdout. If <output-tsv> is omitted,\n"
      "the output is written to a '.tsv' file with the same prefix as <input-pdf>"
      "\n"
      "NOTE: This program was designed for and tested with Chase Sapphire credit card\n"
      "statements. Some aspects of this program may not work for other Chase credit\n"
      "cards.\n"
    )
  )

  (options, args) = op.parse_args()

  if len(args) not in crange(1, 2):
    op.print_help()
    exit(1)

  return (options, args)

###############################################################################

class io_manager(object):
  # output_tsv_file : File object that the output TSV is written to.
  # input_pdf_data  : Array of newline-terminated strings from the PDF.

  def __init__(self, input_pdf_name, output_tsv_name = None):
    if   output_tsv_name == "-":  # Output to stdout.
      self.output_tsv_file = stdout
    elif output_tsv_name is None: # Output to file: input prefix + '.tsv'.
      self.output_tsv_file = open(splitext(input_pdf_name)[0] + ".tsv", "w")
    else:                         # Output to file: user-specified.
      self.output_tsv_file = open(output_tsv_name, "w")

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
    self.output_tsv_file.write(str)

###############################################################################

class month_day(object):
  def __init__(self, month, day):
    self.month = int(month)
    self.day   = int(day)

    assert self.month in crange(1, 12), "Invalid month in date `{}`.".format(self)
    assert self.day   in crange(1, 31), "Invalid day in date `{}`.".format(self)

  def __str__(self):
    return '{0:0>2d}/{1:0>2d}'.format(self.month, self.day)

class month_day_year(month_day):
  def __init__(self, month, day, year):
    # Must be done before we call the base class constructor. Otherwise if an
    # assertion fails in the base class constructor, the overridden __str__ 
    # function (which expects self.year) will fail.
    self.year = int(year)

    super(month_day_year, self).__init__(month, day)

    assert self.year in crange(0, 99), "Invalid year in date `{}`.".format(self)

  def __str__(self):
    return "{0:0>2d}/{1:0>2d}/{2:0>2d}".format(self.month, self.day, self.year)

###############################################################################

class domestic_transaction_record(object):
  def __init__(self, date, description, amount):
    self.date        = date
    self.description = description
    self.amount      = atof(amount)

    #assert type(self.date) is month_day_year,               \
    #  "Transaction date is type `{}` but should be type " + \
    #  "`month_day_year`".format(self.date)

  def __str__(self):
    return "DOMESTIC\t{0}\t{1}\t{2:.2f}".format(
        self.date
      , self.description
      , self.amount
    )

class foreign_transaction_record(domestic_transaction_record):
  def __init__(self, date, description, amount,
                     exchange_date, exchange_currency,
                     exchange_amount, exchange_rate):
    self.exchange_date     = exchange_date
    self.exchange_currency = exchange_currency
    self.exchange_amount   = atof(exchange_amount)
    self.exchange_rate     = atof(exchange_rate)

    super(foreign_transaction_record, self).__init__(date, description, amount)

    #assert type(self.exchange_date) is month_day_year,      \
    #  "Exchange date is type `{}` but should be type "    + \
    #  "`month_day_year`".format(self.exchange_date)

  def __str__(self):
    return "FOREIGN\t{0}\t{1}\t{2:.2f}\t{3}\t{4}\t{5:.2f}\t{6:f}".format(
        self.date
      , self.description
      , self.amount
      , self.exchange_date
      , self.exchange_currency
      , self.exchange_amount
      , self.exchange_rate
    )

###############################################################################

class statement_period_parser(object):
  ############################################################################
  # Grammar.

  # Parse two consecutive digits.
  two_digits_rule = r'[0-9]{2}'

  # Parse a date in MM/DD/YY format.
  month_day_year_rule = r'(' + two_digits_rule + r')/' \
                      + r'(' + two_digits_rule + r')/' \
                      + r'(' + two_digits_rule + r')'

  # Parse a statement period line.
  statement_period_rule = r'Opening/Closing Date '  \
                        + month_day_year_rule       \
                        + r' - '                    \
                        + month_day_year_rule       \
                        + r'$'

  engine = regex_compile(statement_period_rule)
   
  #############################################################################

  def __call__(self, iom):
    match = None

    try:
      while match is None:
        match = self.engine.match(iom.next())
    except StopIteration:
      # The statement period is required, so fail if we don't find one. 
      assert False, "Failed to find statement period in input."

    return (
        month_day_year(match.group(1), match.group(2), match.group(3))
      , month_day_year(match.group(4), match.group(5), match.group(6))
    )

class transaction_header_parser(object):
  # No regex; this parser just uses string comparisons.

  def __call__(self, iom):
    # This parser should not raise an error if it runs out of input before
    # matching. If we don't have any more transaction data blocks, we're done.
    # So, we don't catch StopIterations and let them boil up to
    # statement_parser.
    while True:
      if iom.next() == "Date of":
        # Lookahead to the next line.
        if iom[0] == "Transaction Merchant Name or Transaction Description $ Amount":
          # We matched the second header line. We just need to consume it, and
          # then we are done.
          iom.next()
          return

class transaction_data_parser(object):
  ############################################################################
  # Grammar.

  # Parse two consecutive digits.
  two_digits_rule = r'[0-9]{2}'

  # Parse a date in MM/DD format.
  month_day_rule = r'(' + two_digits_rule + r')/(' + two_digits_rule + r')'

  # Parse a transaction description.
  transaction_description_rule = r'(.*)'

  # Parse a number in N,NNN.NN format.
  positive_quantity_rule = r'[0-9]{1,3}(?:' + r',' + r'[0-9]{3})*' + r'.' + '[0-9]*'

  # Parse a number in -N,NNN.NN format.
  quantity_rule = r'-?' + positive_quantity_rule

  # Parse a transaction amount.
  transaction_amount_rule = r'(-?' + positive_quantity_rule + r')'

  # Parse a domestic transaction record line.
  domestic_transaction_record_rule = month_day_rule               \
                                   + r' '                         \
                                   + transaction_description_rule \
                                   + r' '                         \
                                   + transaction_amount_rule      \
                                   + r'$'

  # Parse an exchange date and currency line.
  exchange_date_and_currency_rule = month_day_rule                \
                                  + r' '                          \
                                  + transaction_description_rule  \
                                  + r'$'
  # NOTE: There is no lookahead assertion here, so this will match a domestic
  # transaction record. First we lookahead and check the exchange rate line
  # (the 3rd line in a foreign transaction record), which is not ambiguous with
  # domestic transaction records, to determine if a transaction record is
  # foreign.

  # Parse an exchange rate quantity.
  exchange_quantity_rule = r'(-?' + positive_quantity_rule + r')'

  # Parse an exchange rate calculation line.
  exchange_rate_calculation_rule = exchange_quantity_rule \
                                 + r' X '                 \
                                 + exchange_quantity_rule \
                                 + r' [(]EXCHG RATE[)]$'

  domestic_transaction_record_engine = regex_compile(domestic_transaction_record_rule)                          
  exchange_date_and_currency_engine  = regex_compile(exchange_date_and_currency_rule)                          
  exchange_rate_calculation_engine   = regex_compile(exchange_rate_calculation_rule)                          
   
  #############################################################################

  # NOTE: audit .next for correct input exhaustion handling.
  # NOTE: Have parsers take a callback to invoke with successful input (semantic action)
  def __call__(self, iom, action):
    while True: 
      domestic_match = self.domestic_transaction_record_engine.match(iom.next())

      if domestic_match is None:
        # We're at the end of the transaction data block.
        return

      # MM/DD to MM/DD/YY conversion is done in the statement_parser, to keep
      # transaction_record_parser from needing tight coupling with
      # statement_period_parser.
      date        = month_day(domestic_match.group(1), domestic_match.group(2))
      description = domestic_match.group(3)
      amount      = domestic_match.group(4)

      # The 1st line of a foreign transaction record has the same format as a
      # domestic transaction record, and the 2nd line of a foreign transaction
      # record requires an in-line lookahead to disambiguate it from a
      # domestic transaction record. The 3rd line requires no in-line
      # lookahead to disambiguate, so we check the 3rd line to determine if
      # the transaction record is foreign or domestic.
      foreign3_match = self.exchange_rate_calculation_engine.match(iom[1])

      if foreign3_match is not None:
        # Foreign transaction record (probably).

        # Confirm that this is a foreign transaction record by checking the
        # 2nd line.
        foreign2_match = self.exchange_date_and_currency_engine.match(iom[0])

        assert foreign2_match is not None,                                  \
          "Foreign transaction record 1st line (date, description and "   + \
          "amount) `{0}` and 3rd line (exchange rate calculation) `{2}` " + \
          "matched, but 2nd line (exchange date and currency) `{1}` did " + \
          "not.".format(domestic_match.string, iom[0], iom[1])

        # Now we definitely have a foreign transaction record, so we consume the
        # two lines we peeked. 
        try:
          iom.next()
          iom.next()
        except StopIteration:
          assert False,                                              \
            "Input ended while consuming peeked lines in foreign " + \
            "transaction match."

        # MM/DD to MM/DD/YY conversion is done in the statement_parser, to keep
        # transaction_record_parser from needing tight coupling with
        # statement_period_parser.
        exchange_date     = month_day(foreign2_match.group(1), foreign2_match.group(2))
        exchange_currency = foreign2_match.group(3)
        exchange_amount   = foreign3_match.group(1)
        exchange_rate     = foreign3_match.group(2)

        action(iom, foreign_transaction_record(date, description, amount,
                                               exchange_date, exchange_currency,
                                               exchange_amount, exchange_rate))

      else:
        # Domestic transaction record.

        action(iom, domestic_transaction_record(date, description, amount))

# TODO: add utility function for month_day -> month_day_year conversion to statement_parser.
class statement_parser(enum(
      "META_DATA_STATE"
    , "TRANSACTION_STATE"
    , "NON_TRANSACTION_STATE"
  ), object):

  # Meta data parsers.
  parse_statement_period   = statement_period_parser()

  # Non transaction parsers.
  parse_transaction_header = transaction_header_parser()

  # Transaction parsers.
  parse_transaction_data   = transaction_data_parser()

  def __init__(self):
    self.state = self.META_DATA_STATE

    # TODO: Move this to IOM.
    # Transaction records don't have the year of the transaction, only have the
    # month and day. We parse the period of the statement, which does have the
    # year (although not the century). We create a mapping of month -> year from
    # the statement period dates and then use it to look up the year of each
    # transaction.
    self.month_year_mapping = {}

  def parse_meta_data(self, iom):
    statement_period = self.parse_statement_period(iom)

    # TODO: Make this an action.

    # Set up the month -> year mappings.
    self.month_year_mapping[statement_period[0].month] = statement_period[0].year
    self.month_year_mapping[statement_period[1].month] = statement_period[1].year

    self.state = self.NON_TRANSACTION_STATE

  def parse_non_transaction(self, iom):
    self.parse_transaction_header(iom)

    self.state = self.TRANSACTION_STATE

  def parse_transaction(self, iom):
    def print_record(iom, record):
      print record

#    self.parse_transaction_data(iom, lambda iom, record: print_record(iom, record))
    self.parse_transaction_data(iom, print_record)

    self.state = self.NON_TRANSACTION_STATE

  def __call__(self, iom):
    print "STATE:", self.state
    if   self.state == self.META_DATA_STATE:
      self.parse_meta_data(iom)
    elif self.state == self.TRANSACTION_STATE:
      self.parse_transaction(iom)
    elif self.state == self.NON_TRANSACTION_STATE:
      self.parse_non_transaction(iom)
    else:
      assert False, "Parser state `{}` is invalid.".format(self.state) 

###############################################################################

(options, args) = parse_command_line()

# Read input file into an array of lines and open the output file.
iom = io_manager(*args)

# Compile parser.
p = statement_parser()

# Parse array of lines and print transactions as we go.
try:
  while True:
    p(iom)
except StopIteration:
  pass

# TESTING: Write pdftotext -raw output. 
#for line in iom:
#  print >> iom, line


