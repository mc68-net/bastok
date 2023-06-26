''' Parser Framework.

    This consists of class `PState`, multable instances of which hold
    parser state, and some generic parsing functions that operate on it.
    Typically further special-purpose parsing functions will be added by
    each particular parser.

    Parsing functions always take a `PState` as the first parameter. They
    may do (almost) any combination of the following:
    - *Consume* input, updating `pos` if successful.
    - *Generate* output, appending the output fragment to `PState.olist`.
    - *Return* a value.
    - *Fail*, consuming and generating nothing and returning an indication
      of failure (but not throwing an exception).
    - *Error*, consuming nothing and raising an exception.

    Typical additional parameters that parsing functions may have are:
    - Something to match. The parser will fail or error if the input at the
      current position does not match this parameter.
    - `genf`: A generator function that is passed the data about to be
      consumed; its return value will be appended to `olist`. Nothing
      is generated if ``genf=None``.
    - `err`: Failure/error flag. When unable to successfully parse the
      input `err=None` will return a failure and anything else will raise
      an error with the that value in the error message/exception.

'''

import  struct

class Parser:
    ''' A parser with mutable state consisting of:

        - An `input` sequence (never mutated) of application-dependent type
          (usually `str` or `bytes`) that is *consumed* by the parser.
        - The current parse position in the input, `pos`.
        - An optional `codec` for translating between Unicode and the
          `input` type when `input` is not a `str`. This should follow the
          `Charset` interface: `trans(n)` for native code point to `str`,
          and `native(s)` for a single Unicode char to native.
        - A `list` `olist` of fragments of parser-dependent type (usually
          `bytes` or `str`) that when joined together are the output of the
          parser. `gen()` appends to this list.

        The parser has two parse points and output lists: "confirmed" and
        "unconfirmed."
        - `start()` sets the unconfirmed parse point to the confirmed parse
          point; and clears any unconfirmed output. this should be used by
          a routine that is not yet sure that it's going to consume the
          following text without an error.
        - Matching routines such as `string()`:
          - On success advance the unconfirmed parse point and return the
            input that matched or a value derived from it.
          - On failure leave the unconfirmed parse point unchanged and
            return `None`.
        - `confirm()` sets the confirmed parse point to the unconfirmed
          parse point and appends all unconfirmed output to the confirmed
          output.

        Thus, parsing routines should `start()`, and either:
        - Parse until they've succeeded, generating output as they go
          along, and then call `confirm()`, or
        - Parse unti they've failed and just return.

        XXX `start()`/`confirm()` possibly should be re-entrant, using
        a stack of confirmed and unconfirmed parse points.
    '''

    def __init__(self, input, codec=None):
        self.input      = input
        self.pos_conf   = 0
        self.pos_un     = 0
        self.olist      = []
        self.codec      = codec

    def remain(self):
        return self.input[self.pos_conf:]

    def start(self):
        self.pos_un = self.pos_conf

    def confirm(self):
        self.pos_conf = self.pos_un

    def string(self, s):
        if isinstance(self.input, str):
            expected = s
        else:
            expected = type(self.input)(map(self.codec.native, s))

        next = self.input[self.pos_un:self.pos_un+len(expected)]
        if expected == next:
            self.pos_un += len(expected)
            return next
        else:
            return None

class PState:
    ''' A mutable parser state, consisting of:

        - An `input` sequence (never mutated) of parser-dependent type
          (usually `str` or `bytes`) that is *consumed* by the parser.
        - The current parse position in the input, `pos`.
        - A `list` `olist` of fragments of parser-dependent type (usually
          `bytes` or `str`) that when joined together are the output of
          the parser.
        - An optional `Charset` for translating between Unicode and
          native-encoded characters, for those parser functions that
          need to do this.

        To enhance modularity and avoid name conflicts, this class does
        not include any parsing functions, just basic handling of
        state and the ability to raise errors.
    '''

    def __init__(self, input, charset=None):
        self.input = input
        self.pos = 0
        self.olist = []
        self.charset = charset

    def finished(self):
        ' Return `true` if we have consumed all input. '
        return self.pos >= len(self.input)

    def consume(self, n=1):
        ''' Consume _n_ elements of the input (default 1)
            and return the consumed input.
            Raise a `ParseError` if we try to consume past end of input.
        '''
        if self.pos + n > len(self.input):
            self.error('Consumed past end of input: {} > {}' \
                .format(self.pos + n, len(self.input)))
        self.pos += n
        return self.input[self.pos-n:self.pos]

    def peek(self):
        ''' Return the next element of the the input sequence, or `None` if
            there is no input left. The parse position is not moved.

            XXX Should this raise an exception if no more input? Perhaps
            should take param like byte().
        '''
        if self.pos >= len(self.input):
            return None
        else:
            return self.input[self.pos]

    def remain(self):
        ' Return the remaining unconsumed input. '
        return self.input[self.pos:]

    def generate(self, x):
        ''' Append an output element to `olist`.
            All elements in the list must be the same type or a subtype
            of the first element added or a `ParseError` will be raised.
        '''
        if len(self.olist) == 0 or isinstance(x, type(self.olist[0])):
            self.olist.append(x)
        else:
            self.error('Cannot generate {}: {} not an instance of {}.' \
                .format(repr(x), type(x), type(self.olist[0])))

    def output(self):
        ''' Return the joined-together `olist`.

            The object used for joining will be a new instance of the class
            of the first object in the list. E.g., if the first object is
            `b'0x01'`, `bytes().join(olist)` will be called.

            If `olist` is empty, `None` will be returned. (XXX This may not
            be the correct behaviour for this case.)
        '''
        if len(self.olist) == 0:
            return None
        cls = type(self.olist[0])
        return cls().join(self.olist)

    def __str__(self):
        p = self.pos
        return 'at {}:{} after …{} …{}'.format(
            p, repr(self.input[p:p+12]),
            repr(self.input[p-12:p]), self.olist[-4:])

    class ParseError(ValueError): pass

    def error(self, message):
        raise self.ParseError(message + ' ' + str(self))

####################################################################
#   Parsing Functions
#
#   These will operate on any state conforming to the interface above.

def byte(p, *, genf=None, err='unexpected end of input'):
    ''' Return the next item in the input sequence, and advance the parse
        position by 1. Despite the name, the return type is determined by
        the underlying sequence (`int` for `bytes`, `str` for `str`).

        This function can fail only when there is no further input. If
        `err` is `None`, `None` will be returned in this case, otherwise a
        `ParseError` will be raised with `err` as the message.

        By default, no output is generated. If `genf` is given the item
        read will be passed to that function and the returned value will be
        appended to the output.
    '''
    if p.finished():
        if err is None: return None
        p.error(err)
    x = p.consume()[0]
    if genf is not None:
        p.generate(genf(x))
    return x

def toksort(toktab, field0=0, field1=1):
    ''' Given a sequence of tuples `toktab`, return a new sequence of
        pairs consisting of index `field0` followed by index `field1`
        of each input tuple, sorted by length of the `field0` entry.

        Regardless of the type of the input sequence and its tuples,
        a `tuple` of `tuple` is always returned.

        This is used to build a token table for use with `toktrans()`
        that matches longer prefixes before shorter.
    '''
    res = [ (f[field0], f[field1]) for f in toktab ]
    return tuple(sorted(res, key=lambda t: len(t[0]), reverse=True))

def toktrans(p, toktab):
    ''' Given a translation table `toktab` of *(x,y)* pairs, try to match
        each *x* in turn against the input at the current parse position.
        The first *x* that matches will cause the matched input to be
        consumed, *y* to be generated (appended to `olist`) and *x* will be
        returned. If no *x* matches, no input will be consumed, nothing
        will be generated, and `None` will be returned.

        If some *x*s are prefixes of other *x*s, you must sort `toktab`
        to place the longer *x*s before their prefixes if you want all
        *x*s to be able to match.

        The input sequence must support the `startswith` function.
    '''
    for x, y in toktab:
        if p.remain().startswith(x):
            p.consume(len(x))
            p.generate(y)
            return x
    return None
