#! /usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
# Copyright (c) 2012-6 Bryce Adelstein Lelbach aka wash <brycelelbach@gmail.com>
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
###############################################################################

###############################################################################
# Grammar for the pdftotext -raw output of a Chase credit card statement PDF:
#
# This is a Parsing Expression Grammar {1} described in Extended Backus-Naur
# Form (please forgive me - old habits of a Boost.Spirit developer) {2, 3, 4, 5}.
# [chars] denotes a regex style character class. There is no whitespace skip
# parsing.
#
# A statement is of a sequence of newline character terminated ("\n") UTF-8
# strings ("lines").
#
# Statements consists of records. Each record is 1 or more consecutive lines.

# There are four types of records: transaction records, transaction header
# records, meta-data records and non-transaction records. 
#
#   statement ::= non_transaction_records meta_data_records (transaction_records | non_transaction_records)*
#
#   non_transaction_records ::= non_transaction_record*
#
#   non_transaction_record ::= [^\n]* "\n"
#
# Meta-data records occur before the first transaction records, and may be
# preceded and followed by non-transaction records. Each type of meta-data
# record occurs exactly once in a statement.
#
#   meta_data_records ::= (non_transaction_record* period_meta_data_record non_transaction_record*) - transaction_header_record
#
#   period_meta_data_record ::= "Opening/Closing Date " month_day_year " - " month_day_year "\n"
#
#   month_day_year ::= two_digits "/" two_digits "/" two_digits
#
#   two_digits ::= [0-9] [0-9]
#
# Sequences of transaction records are always preceded by a transaction record
# header. The header is followed by a sequence of transaction records,
# although there may be non-transaction data after the header before the first
# transaction record (see the section on multi-line transactions and
# page-breaks in Notes).
#
#   transaction_records ::= transaction_header_record non_transaction_records transaction_records
#
#   transaction_header_record ::= "Date of\nTransaction Merchant Name or Transaction Description $ Amount\n"
#
# A transaction record has 3 components: month/day date, description, and amount.
# There are 3 types of transaction records: foreign, transit and domestic.
# 
#   transaction_record ::= foreign_transaction_record | transit_transaction_record | domestic_transaction_record
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
# Foreign transaction records are multi-line extensions of domestic transaction
# records that include currency exchange rate information. They are 3 lines in
# total.
#
#   foreign_transaction_record ::= domestic_transaction_record exchange_info
#
#   exchange_info ::= exchange_date_and_currency exchange_rate_calculation
#
#   exchange_date_and_currency ::= month_day " " transaction_description "\n"
#
#   exchange_rate_calculation ::= quantity " X " positive_quantity " (EXCHG RATE)\n"
#
# Transit transaction records are multi-line extensions of domestic transaction
# records that include travel route information. They are 2 or more lines in
# total.
#
#   transit_transaction_record ::= domestic_transaction_record transit_info
#
#   transit_info ::= transit_leg_with_id transit_leg*
#
#   transit_leg_with_id ::= transit_id " " transit_leg
#
#   transit_leg ::= transit_index " " transit_code " " transit_location " " transit_location
#
#   transit_id ::= [0-9] [0-9] [0-9] [0-9] [0-9] [0-9]
#
#   transit_index ::= [0-9]
#
#   transit_code ::= [A-Z]
#
#   transit_location ::= [A-Z] [A-Z] [A-Z]
#
# {1}: https://ciere.com/cppnow15/x3_docs/spirit/abstracts/parsing_expression_grammar.html
# {2}: https://ciere.com/cppnow15/x3_docs/spirit/introduction.html
# {3}: https://ciere.com/cppnow15/x3_docs/spirit/quick_reference/operator.html
# {4}: https://ciere.com/cppnow15/x3_docs/spirit/quick_reference/directive.html
# {5}: https://ciere.com/cppnow15/x3_docs/spirit/quick_reference/auxiliary.html

###############################################################################
# Notes

# Instead of running a full parser on the entire input, we split it up into an
# array of newline character separated lines, scan for meta-data and transaction
# header records, and then parse those fully. This works nicely because most of
# the multi-line interactions in the parser can be treated as states:
#
# 0.) We start in the "meta-data" state.
# 1.) We look for a meta-data record and skip non-transaction records.
# 2.) When the previous parse succeeds:
#       If there are more meta-data parsers, we pop the current meta-data
#         parser and go to step 0 (no state change).
#       Otherwise, we switch to the "non-transaction" state.
# 3.) We look for a transaction header record and skip non-transaction records.
# 4.) When the previous parse succeeds, we switch to the "pre-transaction" state.
# 5.) We look for a transaction record and skip non-transaction records.
# 6.) When the previous parse succeeds, we switch to the "transaction" state. 
# 7.) We look for transaction records.
# 8.) When the previous parse fails, we switch to the "non-transaction" state
#     and go to step 3.
# 
# Regrettably, there are two more complicated multi-line interaction. Foreign
# and transit transaction records are supersets of the domestic transaction
# record pattern. In addition, foreign transaction records contain newline
# characters followed directly by month/day dates (the same pattern that
# domestic transaction records begin with). This requires lookahead across
# multiple lines (2 lines ahead), which is somewhat unfortunate.
#
# It is possible for multi-line transaction records (e.g. foreign or transit)
# to be page-breaked, such that the transaction record begins in one sequence
# of transaction records and ends in another one. This would cause the second
# sequence of transaction records to be treated as non-transaction records,
# because there will appear to be no transaction records after the transaction
# header record.  Thus, we allow non-transaction records immediately after a
# transaction header record before any transaction records are encountered.
#
# A late fee followed by purchase interest will not parse properly at the moment,
# because a line with a summary of late fees that is not a transaction record is
# placed after the late fee and before the purchase interest.
#
# TODO: The last word of the description seems to always be the location where
#       the transaction occurred (excluding payments). We could parse this.
# TODO: Add support for '-' input, e.g. input from stdin.
# TODO: Transactions records can probably be both foreign and transit, but this
#       is currently not handled.
# TODO: I don't know if numbers in statements are localized differently for
#       non-US customers. Currently localization for numbers is not handled.

###############################################################################
# Protocols

# class Printable(object):
#   def write(self, s : str): ...
#
# Printable objects work with `print`:
#
#   p = Printable()
#   print >> p, "hello world"
#
# class Action(object):
#   def __call__(self, iom, value): ...
#
# class Parser(object):
#   def __call__(self, iom, value_action = lambda iom, value: None) -> bool: ...
#
# Actions are called by Parsers on successful parses.
#
# Each call to a Parser calls an Action at most once.

###############################################################################

from sys import exit, stdout

from os.path import splitext

from subprocess import Popen, PIPE

from optparse import OptionParser

from re import compile as regex_compile
from re import escape  as regex_escape

###############################################################################
# Utilities.

def crange(start, end):
  """Returns the range [start, end]. Equivalent to `range(start, end + 1)`."""
  return range(start, end + 1)

def reduce(reduction, initial_value, sequence):
  """Compute a sum of `sequence` using the binary function `reduction`.

  `initial_value` is the left-hand input to the first call to `reduction`.
  """
  for item in sequence:
    initial_value = reduction(initial_value, item)
  return initial_value

def str_to_float(string):
  """Converts a `str` representing a number to a `float`. Supports thousands separators."""
  return float(string.replace(",", ""))

class string_escaper(object):
  """Escape all control characters in `string`.

  Loosely based on: https://stackoverflow.com/a/93029/3304954
  """

  control_char_engine = regex_compile(u"([{0}])".format(regex_escape(
    "".join(map(unichr, range(0, 32) + range(127, 160)))
  )))

  def __call__(self, string):
    return self.control_char_engine.sub(
        lambda match: r'\x{0:02x}'.format(ord(match.group()))
      , string
    )

escape_str = string_escaper()

def enum(*states):
  """Create a new class that has an attribute of unique type for each `str` in `states`."""
  attrs = dict(map(lambda n: (n, type(n, (), dict(__repr__ = lambda s: n))()), states))
  return type("enum", (), attrs)

###############################################################################

def parse_command_line():
  op = OptionParser(
    usage=(
             "%prog [options] <input-pdf>\n"
      "       %prog [options] <input-pdf> <output-tsv>\n"
      "\n"
      "Extracts transaction records from a Chase credit card statement PDF and writes it\n"
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

  op.add_option(
      "-n", "--no-header",
      help=("Do not write a header row that describes each column."),
      action="store_false", dest="header", default=True
  )

  op.add_option(
      "-d", "--debug",
      help=("Print all records parsed and debugging information, and omit the "
            "header row."),
      action="store_true", dest="debug", default=False
  )

  (options, args) = op.parse_args()

  if len(args) not in crange(1, 2):
    op.print_help()
    exit(1)

  return (options, args)

###############################################################################

class month_day(object):
  """A MM/DD date.

  Attributes:
    month (int) : The month of the year (between 1 and 12).
    day   (int) : The day of the month (between 1 and 31).
  """

  def __init__(self, month, day):
    self.month = month
    self.day   = day

    assert self.month in crange(1, 12), "Invalid month in date `{0}`.".format(self)
    assert self.day   in crange(1, 31), "Invalid day in date `{0}`.".format(self)

  def __str__(self):
    return '{0:0>2d}/{1:0>2d}'.format(self.month, self.day)

class month_day_year(month_day):
  """A MM/DD/YY date.

  Attributes:
    month (int) : The month of the year (between 1 and 12).
    day   (int) : The day of the month (between 1 and 31).
    year  (int) : The year of the century (between 0 and 99).
  """

  def __init__(self, month, day, year):
    # Must be done before we call the base class constructor. Otherwise if an
    # assertion fails in the base class constructor, the overridden __str__ 
    # function (which expects self.year) will fail.
    self.year = year

    super(month_day_year, self).__init__(month, day)

    assert self.year in crange(0, 99), "Invalid year in date `{0}`.".format(self)

  def __str__(self):
    return "{0:0>2d}/{1:0>2d}/{2:0>2d}".format(self.month, self.day, self.year)

class period(object):
  """A range of time defined by two MM/DD/YY dates (`month_day_year`s).

  The range is closed, e.g. `[opening, closing]`.

  Attributes:
    opening (:obj:`month_day_year`) : The starting date.
    closing (:obj:`month_day_year`) : The ending date.
  """

  def __init__(self, opening, closing):
    self.opening = opening
    self.closing = closing

    # TODO: Validate that opening is earlier than closing.

class transit_leg(object):
  """A representation of a ticket for a single leg of a trip.

  Attributes:
    code      (str) : The ticket type, described by a single letter.
    departure (str) : The departure point, described by three letters.
    arrival   (str) : The arrival point, described by three letters.
  """

  def __init__(self, code, departure, arrival):
    self.code   = code
    self.departure = departure
    self.arrival = arrival

    assert type(self.code)      is str and len(self.code) == 1,       \
      "Invalid code `{0}` in transit leg `{1}`".format(self.code, self)
    assert type(self.departure) is str and len(self.departure) == 3,  \
      "Invalid departure `{0}` in transit leg `{1}`".format(self.departure, self)
    assert type(self.arrival)   is str and len(self.arrival) == 3,    \
      "Invalid arrival `{0}` in transit leg `{1}`".format(self.arrival, self)

  def __str__(self):
    return "{0}({1}->{2})".format(self.code, self.departure, self.arrival)

###############################################################################

class domestic_transaction_record(object):
  """A Chase credit card domestic transaction record.

  Attributes:
    date (:obj:`month_day_year`) :
      Transaction date.
    description (str) :
      Transaction description (newline-free).
    amount (float) :
      Transaction amount in domestic currency. 
  """

  def __init__(self, date, description, amount):
    self.date        = date
    self.description = description
    self.amount      = amount

  def __str__(self):
    return "DOMESTIC\t{0}\t{1}\t{2:.2f}".format(
        self.date
      , self.description
      , self.amount
    )

class foreign_transaction_record(domestic_transaction_record):
  """A Chase credit card foreign transaction record.

  Attributes:
    date (:obj:`month_day_year`) :
      Transaction date.
    description (str) :
      Transaction description (newline-character-free).
    amount (float) :
      Transaction amount in domestic currency. 
    exchange_date (:obj:`month_day_year`) :
      Date of the currency exchange.
    exchange_currency (str) :
      Name of the foreign currency (newline-character-free).
    exchange_amount (float) :
      Currency exchange amount in the foreign currency `exchange_currency`. 
    exchange_rate (float) :
      Currency exchange rate.
  """

  def __init__(self, date, description, amount,
                     exchange_date, exchange_currency,
                     exchange_amount, exchange_rate):
    self.exchange_date     = exchange_date
    self.exchange_currency = exchange_currency
    self.exchange_amount   = exchange_amount
    self.exchange_rate     = exchange_rate

    super(foreign_transaction_record, self).__init__(date, description, amount)

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

class transit_transaction_record(domestic_transaction_record):
  """A Chase credit card transit transaction record.

  Attributes:
    date (:obj:`month_day_year`) :
      Transaction date.
    description (str) :
      Transaction description (newline-character-free).
    amount (float) :
      Transaction amount in domestic currency. 
    transit_id (int) :
      A six-digit identifier (meaning unknown, may identify the vendor or the
      type of transit).
    transit_legs (:obj:`list` of :obj:`transit_leg`s) :
      A non-empty list of `transit_leg`s describing the trip. 
  """

  def __init__(self, date, description, amount,
                     transit_id, transit_legs):
    self.transit_id   = transit_id
    self.transit_legs = transit_legs

    super(transit_transaction_record, self).__init__(date, description, amount)

  def __str__(self):
    return "TRANSIT\t{0}\t{1}\t{2:.2f}\t\t\t\t\t{3:0>6d}\t{4}".format(
        self.date
      , self.description
      , self.amount
      , self.transit_id
      , reduce(
            lambda x, y: "{0} {1}".format(str(x), str(y))
          , ""
          , self.transit_legs
        )
    )

###############################################################################

class io_manager(object):
  """Manages I/O for a single Chase credit card statement PDF to TSV conversion.

  `io_manager` is responsible for both file I/O and the parser input stream,
  which is a list of UTF-8 strings read from the input PDF using the `pdftotext`
  command line utility.

  It is Iterable and an Iterator; it can be treated like a stream of input
  lines. It also supports lookahead via the index operator. For example::

    iom = io_manager(input_name)

    line = iom.next() # Access and consume the next line of input.
    line = iom[0]     # Access the next line of input without consuming it.
    line = iom[1]     # Access the 2nd line of input without consuming it.
    line = iom[n]     # Access the `(n + 1)`th line of input without consuming it.

  `io_manager` also maintains a `dict` mapping months to years, which is used
  to convert `month_day`s to `month_day_year`s.

  Attributes:
    output_tsv_file    (file) : File object that the output TSV is written to.
    input_sequence     (list) : List of lines (`str`) from the input PDF.
    month_year_mapping (dict) : Mapping used to add years to transaction records.
  """

  def __init__(self, input_pdf_name, output_tsv_name = None):
    if   output_tsv_name == "-":  # Output to stdout.
      self.output_tsv_file = stdout
    elif output_tsv_name is None: # Output to file: input prefix + '.tsv'.
      self.output_tsv_file = open(splitext(input_pdf_name)[0] + ".tsv", "w")
    else:                         # Output to file: user-specified.
      self.output_tsv_file = open(output_tsv_name, "w")

    # Launch a subprocess that extracts the text from the input PDF.
    pdftotext = Popen(["pdftotext", "-raw", input_pdf_name, "-"], stdout = PIPE)

    # Split the input into an list of lines.
    self.input_sequence = pdftotext.communicate()[0].split("\n")

    # Reverse the list of lines because we'll be popping lines from the list
    # starting with the 1st, and removing from the end is more efficient - O(1)
    # vs O(N) (I don't actually know if python lists are implemented as dynamic
    # arrays, but I assume so).
    self.input_sequence.reverse()

    # Transaction records don't have the year of the transaction, only have the
    # month and day. We parse the period of the statement, which does have the
    # year (although not the century). We create a mapping of month to year from
    # the statement period dates and then use it to look up the year of each
    # transaction.
    self.month_year_mapping = {}

  #############################################################################
  # Input Stream

  def __iter__(self):
    """Return an iterator to the input sequence.

    This is a requirement for the `Iterable` protocol.
    """
    return self

  def next(self):
    """Consume and return the next line in the input.

    This is a requirement for the `Iterator` protocol.

    Raises:
      StopIteration : If there is no more input.
    """
    if len(self.input_sequence) == 0:
      raise StopIteration()

    return self.input_sequence.pop()

  # Lookahead at the (n + 1)th line. 
  def __getitem__(self, n):
    """Access the `(n + 1)`th line of input without consuming it.

    Returns:
      The `(n + 1)`th line of input if it exists, otherwise an empty `str`.
    """
    if len(self.input_sequence) <= n:
      # We don't want to terminate on a peek.
      return ''

    return self.input_sequence[-(n + 1)]

  #############################################################################
  # Output

  def write(self, s):
    """Write a string to the output TSV file.

    This is a requirement for the `Printable` protocol.
    """
    self.output_tsv_file.write(s)

  #############################################################################
  # Month to Year Mapping

  def add_month_year_mapping(self, t):
    """Add the month and year from `t` to the month to year mapping.

    `t` can be either a `month_day_year` or a `period` object.

    This function overwrites existing mappings if there is any overlap.

    Fulfills the `Action` protocol and can be passed to
    `period_meta_data_record_parser`.

    Raises:
      AssertionError : If `type(t)` is not `month_day_year` or `period`.
    """
    if   type(t) is month_day_year:
      self.month_year_mapping[t.month] = t.year
    elif type(t) is period:
      self.add_month_year_mapping(t.opening)
      self.add_month_year_mapping(t.closing)
    else:
      assert False,                                                           \
        "Cannot add `{0}` of type `{1}` to the month year mapping because " + \
        "it is not a `month_day_year` or `period`.".format(t, type(t))

  def add_year(self, date):
    """Add the year to a `month_day` using the month to year mapping.

    Returns:
      A `month_day_year` object with the same month and day as `date`.

    Raises:
      AssertionError : If there is no month to year mapping for `date.month`.
    """
    assert date.month in self.month_year_mapping,                            \
      "The month of `month_day` `{0}` was not found in the month to year " + \
      "mapping {1}".format(date.month, self.month_year_mapping)

    return month_day_year(date.month, date.day, self.month_year_mapping[date.month])

###############################################################################

class period_meta_data_record_parser(object):
  """A `Parser` that matches a single period meta-data record.

  The value passed to the `Action` on a successful parse is a `period`.
  """

  ############################################################################
  # Grammar

  # Parse two consecutive digits.
  two_digits_rule = r'[0-9]{2}'

  # Parse a date in MM/DD/YY format.
  month_day_year_rule = r'(' + two_digits_rule + r')/' \
                      + r'(' + two_digits_rule + r')/' \
                      + r'(' + two_digits_rule + r')'

  # Parse a statement period line.
  period_meta_data_rule = r'Opening/Closing Date '  \
                        + month_day_year_rule       \
                        + r' - '                    \
                        + month_day_year_rule       \
                        + r'$'

  period_meta_data_engine = regex_compile(period_meta_data_rule)
   
  #############################################################################

  def __call__(self, iom, action = lambda iom, value: None):
    match = self.period_meta_data_engine.match(iom[0])

    if match is None:
      return False

    # We matched, so we consume the input.
    try:
      iom.next()
    except StopIteration:
      assert False,                                                         \
        "Input ended while consuming peeked lines after period meta-data" + \
        "record match."

    opening = month_day_year(int(match.group(1)),
                             int(match.group(2)),
                             int(match.group(3)))
    closing = month_day_year(int(match.group(4)),
                             int(match.group(5)),
                             int(match.group(6)))

    action(iom, period(opening, closing))

    return True

###############################################################################

class always_match_parser(object):
  """A `Parser` that always succeeds if there is input available and fails otherwise.

  It passes the next line to its `Action` verbatim."""
  def __call__(self, iom, action = lambda iom, value: None):
    try:
      action(iom, iom.next())
      return True
    except StopIteration:
      return False

###############################################################################

class non_transaction_record_parser(always_match_parser):
  """A `Parser` that matches a single non-transaction record.

  This `Parser` inherits from `always_match_parser`. It always succeeds if
  there is input available, fails otherwise, and passes the next line to its
  `Action` after escaping it.
  """
  def __call__(self, iom, action = lambda iom, value: None):
    return super(non_transaction_record_parser, self).__call__(
        iom
      , lambda iom, value: action(iom, escape_str(value))
    )

###############################################################################

class transaction_header_record_parser(object):
  """A `Parser` that matches a transaction header record.

  The transaction header pattern, with the newline character replaced with a
  "\\n", is the value passed to the `Action` on a successful parse.

  This parser uses simple string comparisons instead of regular expressions.
  """

  def __call__(self, iom, action = lambda iom: None):
    if iom[0] == "Date of":
      # Likely the start of a transaction header record, lookahead to the next line.
      if iom[1] == "Transaction Merchant Name or Transaction Description $ Amount":
        # We matched the second header line. We just need to consume the input,
        # call our action, and return True.

        try:
          action(iom, iom.next() + "\\n" + iom.next())
        except StopIteration:
          assert False,                                                     \
            "Input ended while consuming peeked lines after transaction " + \
            "header record match."

        return True

    else:
      # No match. 
      return False

###############################################################################

class transaction_record_parser(object):
  """A Parser that matches a single transaction record.

  The value passed to the `Action` on a successful parse is either a
  `domestic_transaction_record`, a `foreign_transaction_record` or a
  `transit_transaction_record`.
  """

  ############################################################################
  # Grammar

  # Parse one digit.
  one_digit_rule = r'[0-9]'

  # Parse two consecutive digits.
  two_digits_rule = r'[0-9]{2}'

  # Parse six consecutive digits.
  six_digits_rule = r'[0-9]{6}'

  # Parse one capital letter.
  one_capital_letter_rule = r'[A-Z]'

  # Parse three consecutive capital letters.
  three_capital_letters_rule = r'[A-Z]{3}'

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
  # There is no lookahead assertion here, so this will match a domestic
  # transaction record. First we lookahead and check the exchange rate line
  # (the 3rd line in a foreign transaction record), which is not ambiguous with
  # domestic transaction records, to determine if a transaction record is
  # foreign.

  # Parse a currency exchange amount.
  exchange_amount_rule = r'(' + quantity_rule + r')'

  # Parse a currency exchange rate.
  exchange_rate_rule = r'(' + positive_quantity_rule + r')'

  # Parse a currency exchange rate calculation line.
  exchange_rate_calculation_rule = exchange_amount_rule   \
                                 + r' X '                 \
                                 + exchange_rate_rule     \
                                 + r' [(]EXCHG RATE[)]$'

  # Parse a transit index.
  transit_index_rule = one_digit_rule
  # We do not capture and use the index, as it's implicit in the structure of
  # the data.

  # Parse a transit code.
  transit_code_rule = r'(' + one_capital_letter_rule + r')'

  # Parse a transit location.
  transit_location_rule = r'(' + three_capital_letters_rule + r')'

  # Parse a transit leg line.
  transit_leg_rule = transit_index_rule     \
                   + r' '                   \
                   + transit_code_rule      \
                   + r' '                   \
                   + transit_location_rule  \
                   + r' '                   \
                   + transit_location_rule  \
                   + r'$'

  # Parse a transit id.
  transit_id_rule = r'(' + six_digits_rule + r')'

  # Parse a transit id followed by a transit leg.
  transit_leg_with_id_rule = transit_id_rule + r' ' + transit_leg_rule

  domestic_transaction_record_engine = regex_compile(domestic_transaction_record_rule)
  exchange_date_and_currency_engine  = regex_compile(exchange_date_and_currency_rule)
  exchange_rate_calculation_engine   = regex_compile(exchange_rate_calculation_rule)
  transit_leg_engine                 = regex_compile(transit_leg_rule)
  transit_leg_with_id_engine         = regex_compile(transit_leg_with_id_rule)

  #############################################################################

  def __call__(self, iom, action = lambda iom, value: None):
    domestic_match = self.domestic_transaction_record_engine.match(iom[0])

    if domestic_match is None:
      return False

    # We matched, so we consume the input.
    try:
      iom.next()
    except StopIteration:
      assert False,                                                  \
        "Input ended while consuming peeked lines after domestic " + \
        "transaction record match."

    date        = iom.add_year(month_day(int(domestic_match.group(1)),
                                         int(domestic_match.group(2))))
    description = escape_str(domestic_match.group(3))
    amount      = str_to_float(domestic_match.group(4))

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
        assert False,                                                 \
          "Input ended while consuming peeked lines after foreign " + \
          "transaction record match."

      # MM/DD to MM/DD/YY conversion is done in the statement_parser, to keep
      # transaction_record_parser from needing tight coupling with
      # period_meta_data_record_parser.
      exchange_date     = iom.add_year(month_day(int(foreign2_match.group(1)),
                                                 int(foreign2_match.group(2))))
      exchange_currency = escape_str(foreign2_match.group(3))
      exchange_amount   = str_to_float(foreign3_match.group(1))
      exchange_rate     = str_to_float(foreign3_match.group(2))

      action(iom, foreign_transaction_record(date, description, amount,
                                             exchange_date, exchange_currency,
                                             exchange_amount, exchange_rate))

    else:
      # Domestic or transit transaction record.

      # Check if the next line is transit info.
      transit2_match = self.transit_leg_with_id_engine.match(iom[0])

      if transit2_match is not None:
        # We definitely have a transit transaction record with at least 2 lines,
        # so consume the 2nd line that we peeked.
        try:
          iom.next()
        except StopIteration:
          assert False,                                                 \
            "Input ended while consuming peeked lines after transit " + \
            "transaction record match."

        transit_id = int(transit2_match.group(1))

        transit_legs = [
          transit_leg(transit2_match.group(2),
                      transit2_match.group(3),
                      transit2_match.group(4))
        ]

        # Now, iteratively match any additional transit leg lines.
        while True:
          transitN_match = self.transit_leg_engine.match(iom[0])

          if transitN_match is not None:
            # We matched so consume the line.
            try:
              iom.next()
            except StopIteration:
              assert False,                                                 \
                "Input ended while consuming peeked lines after transit " + \
                "transaction record match."

            # Add the transit leg to the list.
            transit_legs.append(
              transit_leg(transitN_match.group(1),
                          transitN_match.group(2),
                          transitN_match.group(3))
            )
          else:
            # No match, so that's the end of the transit transaction record and
            # we need to break out of the while loop.
            break

        action(iom, transit_transaction_record(date, description, amount,
                                               transit_id, transit_legs))

      else:
        # Domestic transaction record.

        action(iom, domestic_transaction_record(date, description, amount))

    return True

###############################################################################

class record_parser(enum(
      "META_DATA_STATE"
    , "NON_TRANSACTION_STATE"
    , "PRE_TRANSACTION_STATE"
    , "TRANSACTION_STATE"
  ), object):
  """A state machine `Parser` that matches a single record. 
  
  The value passed to the `Action` is a tuple with three elements: the current
  state of the parser, the sub-parser and the sub-parser value.

  Returns:
    False if the input is exhausted and True otherwise.

  Attributes:
    state             (enum) : The current state of the parser.
    meta_data_parsers (list) : A list of meta-data parsers to run. They are
      stored in reverse order so that the next meta-data parser can be popped
      from the end of the list instead of the beginning.
  """

  # Non-transaction parsers.
  parse_transaction_header_record = transaction_header_record_parser()
  parse_non_transaction_record    = non_transaction_record_parser()

  # Transaction parsers.
  parse_transaction_record        = transaction_record_parser()

  def __init__(self):
    self.state = self.META_DATA_STATE

    # List of pairs of meta-data parsers and actions. This is reversed so that
    # we can write it in order, but pop from the end of the list instead of the
    # beginning, which is more efficient.
    self.meta_data_parsers = list(reversed([
        (period_meta_data_record_parser(), io_manager.add_month_year_mapping)
    ]))

  def bind_action(self, sub_parser, user_action,
                                    our_action = lambda iom, value: None):
    """Create a single action that invokes `user_action` and `our_action`.

    `user_action` is passed the parser state (`self.state`) and `sub_parser`
    when called.
    """
    def binder(self, sub_parser, iom, user_action, our_action, value):
      our_action(iom, value)
      user_action(iom, (self.state, sub_parser, value))
    return lambda iom, value: binder(self, sub_parser, iom,           \
                                     user_action, our_action, value)

  def __call__(self, iom, action = lambda iom, value: None):
    if   self.state == self.META_DATA_STATE:
      assert len(self.meta_data_parsers) > 0,                            \
        "`record_parser` is in META_DATA_STATE but there are no more " + \
        "meta-data parsers"

      (meta_data_parser, meta_data_action) = self.meta_data_parsers[-1]

      # Wrap the user-specified action and the meta-data action. 
      bound_action = self.bind_action(meta_data_parser, action, meta_data_action)

      # Try to match with the current meta-data parser.
      if meta_data_parser(iom, bound_action):
        # We matched, so pop the meta-data parser.
        self.meta_data_parsers.pop()

        if len(self.meta_data_parsers) == 0:
          # We don't have any more meta-data parsers to run, so switch to the
          # non-transaction state.
          self.state = self.NON_TRANSACTION_STATE

        return True

    elif self.state == self.NON_TRANSACTION_STATE:
      # Wrap the user-specified action to pass it the parser state and sub-parser.
      bound_action = self.bind_action(self.parse_transaction_header_record, action)

      # Try to match with the transaction header record parser.
      if self.parse_transaction_header_record(iom, bound_action):
        # We matched, so switch to the pre-transaction state.
        self.state = self.PRE_TRANSACTION_STATE
        return True

    elif self.state == self.PRE_TRANSACTION_STATE:
      # Wrap the user-specified action to pass it the parser state and sub-parser.
      bound_action = self.bind_action(self.parse_transaction_record, action)

      # Try to match with the transaction record parser.
      if self.parse_transaction_record(iom, bound_action):
        # We matched, so switch to the transaction state.
        self.state = self.TRANSACTION_STATE
        return True

    elif self.state == self.TRANSACTION_STATE:
      # Wrap the user-specified action to pass it the parser state and sub-parser.
      bound_action = self.bind_action(self.parse_transaction_record, action)

      # Try to match with the transaction record parser.
      if self.parse_transaction_record(iom, bound_action):
        # We didn't fail, so we stay in the transaction state. 
        return True
      else:
        # We failed, so we switch to the non-transaction state.
        self.state = self.NON_TRANSACTION_STATE

    else:
      assert False, "Parser state `{0}` is invalid.".format(self.state) 

    # We didn't match anything else, so we must be on a non-transaction record
    # or out of input.

    # Wrap the user-specified action to pass it the parser state and sub-parser.
    bound_action = self.bind_action(self.parse_non_transaction_record, action)

    if self.parse_non_transaction_record(iom, bound_action):
      # We didn't fail, so there was input.
      return True
    else:
      # We failed, so we must be out of input. This is the only path that causes
      # a `record_parser` to return False.
      return False

###############################################################################

(options, args) = parse_command_line()

# Read input file into an list of lines and open the output file.
iom = io_manager(*args)

# Compile parser.
p = record_parser()

# Print the TSV header.
if options.header and not options.debug:
  print >> iom, "Transaction Type\t"                                            + \
                "Transaction Date\t"                                            + \
                "Transaction Description\t"                                     + \
                "Amount [Domestic Currency]\t"                                  + \
                "Currency Exchange Date\t"                                      + \
                "Foreign Currency\t"                                            + \
                "Amount [Foreign Currency]\t"                                   + \
                "Currency Exchange Rate [Foreign Currency/Domestic Currency]\t" + \
                "Transit ID\t"                                                  + \
                "Transit Legs"

action = None

if options.debug:
  # Debug output mode: print debug info and all records.
  def print_any_record(iom, tup):
    (state, sub_parser, value) = tup
    print >> iom, "{0}\t{1}\t{2}".format(state, sub_parser, value)

  action = print_any_record

else:
  # Regular output mode: print transaction records only.
  def print_transaction_record(iom, tup):
    (state, sub_parser, value) = tup
    if type(sub_parser) == transaction_record_parser:
      print >> iom, value

  action = print_transaction_record

# Parse the input and output as we go.
while p(iom, action): pass

