class ParserRegistry:
    def __init__(self):
        self._parsers = []

    def register(self, parser):
        self._parsers.append(parser)
        return parser

    def match(self, item):
        for parser in self._parsers:
            if parser.can_parse(item):
                return parser
        return None

    def all(self):
        return list(self._parsers)


parser_registry = ParserRegistry()
