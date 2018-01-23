"""This module implements a CYK parser."""
from collections import defaultdict
import itertools
import re

from ..common import ParseError, Terminal, Terminal_Regexp
from ..lexer import Token
from ..tree import Tree


def TypeName(x):
  return type(x).__name__


class Symbol(object):
  """Any grammar symbol."""

  def __init__(self, s):
    self.s = s

  def __repr__(self):
    return '%s(%s)' % (TypeName(self), str(self))

  def __str__(self):
    return str(self.s)

  def __eq__(self, other):
    return str(self) == str(other)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(TypeName(self) + '&' + self.__str__())


class T(Symbol):
  """Terminal."""

  def __init__(self, s):
    super(T, self).__init__(s)
    self.regexp = re.compile(s)

  def match(self, s):
    m = self.regexp.match(s)
    return bool(m) and len(m.group(0)) == len(s)

  def __eq__(self, other):
    return super(T, self).__eq__(other) and isinstance(other, T)


class NT(Symbol):
  """Non-terminal."""

  def __eq__(self, other):
    return super(NT, self).__eq__(other) and isinstance(other, NT)


class Rule(object):
  """Context-free grammar rule."""

  def __init__(self, lhs, rhs, weight, alias):
    super(Rule, self).__init__()
    assert isinstance(lhs, NT), lhs
    assert all(isinstance(x, NT) or isinstance(x, T) for x in rhs), rhs
    self.lhs = lhs
    self.rhs = rhs
    self.weight = weight
    self.alias = alias

  def __str__(self):
    return '%s -> %s' % (str(self.lhs), ' '.join(str(x) for x in self.rhs))

  def __repr__(self):
    return str(self)

  def __hash__(self):
    return hash(self.__repr__())

  def __eq__(self, other):
    return self.lhs == other.lhs and self.rhs == other.rhs

  def __ne__(self, other):
    return not self.__eq__(other)


class Grammar(object):
  """Context-free grammar."""

  def __init__(self, rules):
    super(Grammar, self).__init__()
    self.rules = sorted(rules, key=lambda x: str(x))

  def __eq__(self, other):
    return set(self.rules) == set(other.rules)

  def __str__(self):
    return '\n' + '\n'.join(sorted(x.__repr__() for x in self.rules)) + '\n'

  def __repr__(self):
    return str(self)


# Parse tree data structures
class RuleNode(object):
  """A node in the parse tree, which also contains the full rhs rule."""

  def __init__(self, rule, children, weight=0):
    super(RuleNode, self).__init__()
    self.rule = rule
    self.children = children
    self.weight = weight

  def __repr__(self):
    return 'RuleNode(%s, [%s])' % (repr(self.rule.lhs), ', '.join(
        str(x) for x in self.children))

  def __hash__(self):
    return hash(self.__repr__())


class Node(object):
  """A node in the parse tree."""

  def __init__(self, lhs, children):
    super(Node, self).__init__()
    self.lhs = lhs
    self.children = children

  def __repr__(self):
    return 'Node(%s, [%s])' % (repr(self.lhs), ', '.join(
        str(x) for x in self.children))

  def __hash__(self):
    return hash(self.__repr__())


class Parser(object):
  """Parser wrapper."""

  def __init__(self, rules, start):
    super(Parser, self).__init__()
    self.orig_rules = {rule.alias: rule for rule in rules}
    rules = [self._ToRule(rule) for rule in rules]
    self.grammar = ToCnf(Grammar(rules))
    self.start = NT(start)

  def _ToRule(self, lark_rule):
    """Converts a lark rule, (lhs, rhs, callback, options), to a Rule."""
    return Rule(
        NT(lark_rule.origin), [
            T(x.data) if (isinstance(x, Terminal_Regexp) or
                          isinstance(x, Terminal)) else NT(x)
            for x in lark_rule.expansion
        ], weight=lark_rule.options.priority if lark_rule.options and lark_rule.options.priority else 0, alias=lark_rule.alias)

  def parse(self, tokenized):  # pylint: disable=invalid-name
    """Parses input, which is a list of tokens."""
    table, trees = _Parse(tokenized, self.grammar)
    # Check if the parse succeeded.
    if all(r.lhs != self.start for r in table[(0, len(tokenized) - 1)]):
      raise ParseError('Parsing failed.')
    parse = trees[(0, len(tokenized) - 1)][NT(self.start)]
    return self._ToTree(RevertCnf(parse))

  def _ToTree(self, rule_node):
    """Converts a RuleNode parse tree to a lark Tree."""
    orig_rule = self.orig_rules[rule_node.rule.alias]
    children = []
    for i, child in enumerate(rule_node.children):
      if isinstance(child, RuleNode):
        children.append(self._ToTree(child))
      elif isinstance(child, Terminal_Regexp):
        children.append(Token(orig_rule.expansion[i].name, child.s))
      else:
        children.append(Token(orig_rule.expansion[i], child.s))
    return Tree(orig_rule.origin, children, rule=orig_rule)


def PrintParse(node, indent=0):
  if isinstance(node, RuleNode):
    print(' ' * (indent * 2) + str(node.rule.lhs))
    for child in node.children:
      PrintParse(child, indent + 1)
  else:
    print(' ' * (indent * 2) + str(node.s))


def _Parse(s, g):
  """Parses sentence 's' using CNF grammar 'g'."""
  # The CYK table. Indexed with a 2-tuple: (start pos, end pos)
  table = defaultdict(set)
  # Top-level structure is similar to the CYK table. Each cell is a dict from
  # rule name to the best (lightest) tree for that rule.
  trees = defaultdict(dict)
  # Populate base case with existing terminal production rules
  for i, w in enumerate(s):
    for terminal, rules in g.terminal_rules.iteritems():
      if terminal.match(w):
        for rule in rules:
          table[(i, i)].add(rule)
          if (rule.lhs not in trees[(i, i)] or
              rule.weight < trees[(i, i)][rule.lhs].weight):
            trees[(i, i)][rule.lhs] = RuleNode(rule, [T(w)], weight=rule.weight)
  # Iterate over lengths of sub-sentences
  for l in xrange(2, len(s) + 1):
    # Iterate over sub-sentences with the given length
    for i in xrange(len(s) - l + 1):
      # Choose partition of the sub-sentence in [1, l)
      for p in xrange(i + 1, i + l):
        span1 = (i, p - 1)
        span2 = (p, i + l - 1)
        for r1, r2 in itertools.product(table[span1], table[span2]):
          for rule in g.nonterminal_rules.get((r1.lhs, r2.lhs), []):
            table[(i, i + l - 1)].add(rule)
            r1_tree = trees[span1][r1.lhs]
            r2_tree = trees[span2][r2.lhs]
            rule_total_weight = rule.weight + r1_tree.weight + r2_tree.weight
            if (rule.lhs not in trees[(i, i + l - 1)] or
                rule_total_weight < trees[(i, i + l - 1)][rule.lhs].weight):
              trees[(i, i + l - 1)][rule.lhs] = RuleNode(rule, [r1_tree, r2_tree], weight=rule_total_weight)
  return table, trees


# This section implements context-free grammar converter to Chomsky normal form.
# It also implements a conversion of parse trees from its CNF to the original
# grammar.
# Overview:
# Applies the following operations in this order:
# * TERM: Eliminates non-solitary terminals from all rules
# * BIN: Eliminates rules with more than 2 symbols on their right-hand-side.
# * UNIT: Eliminates non-terminal unit rules
#
# The following grammar characteristics aren't featured:
# * Start symbol appears on RHS
# * Empty rules (epsilon rules)


class CnfWrapper(object):
  """CNF wrapper for grammar.

  Validates that the input grammar is CNF and provides helper data structures.
  """

  def __init__(self, grammar):
    super(CnfWrapper, self).__init__()
    self.grammar = grammar
    self.rules = grammar.rules
    self.terminal_rules = defaultdict(list)
    self.nonterminal_rules = defaultdict(list)
    for r in self.rules:
      # Validate that the grammar is CNF and populate auxiliary data structures.
      assert isinstance(r.lhs, NT), r
      assert len(r.rhs) in [1, 2], r
      if len(r.rhs) == 1 and isinstance(r.rhs[0], T):
        self.terminal_rules[r.rhs[0]].append(r)
      elif len(r.rhs) == 2 and all(isinstance(x, NT) for x in r.rhs):
        self.nonterminal_rules[tuple(r.rhs)].append(r)
      else:
        assert False, r

  def __eq__(self, other):
    return self.grammar == other.grammar

  def __repr__(self):
    return self.grammar.__repr__()


class UnitSkipRule(Rule):
  """A rule that records NTs that were skipped during transformation."""

  def __init__(self, lhs, rhs, skipped_rules, weight, alias):
    super(UnitSkipRule, self).__init__(lhs, rhs, weight, alias)
    self.skipped_rules = skipped_rules

  def __eq__(self, other):
    return (super(UnitSkipRule, self).__eq__(other) and
            isinstance(other, type(self)) and
            self.skipped_rules == other.skipped_rules)


def BuildUnitSkipRule(unit_rule, target_rule):
  skipped_rules = []
  if isinstance(unit_rule, UnitSkipRule):
    skipped_rules += unit_rule.skipped_rules
  skipped_rules.append(target_rule)
  if isinstance(target_rule, UnitSkipRule):
    skipped_rules += target_rule.skipped_rules
  return UnitSkipRule(unit_rule.lhs, target_rule.rhs, skipped_rules,
                      weight=unit_rule.weight + target_rule.weight, alias=unit_rule.alias)


def GetAnyNtUnitRule(g):
  """Returns a non-terminal unit rule from 'g', or None if there is none."""
  for rule in g.rules:
    if len(rule.rhs) == 1 and isinstance(rule.rhs[0], NT):
      return rule
  return None


def RemoveUnitRule(g, rule):
  """Removes 'rule' from 'g' without changing the langugage produced by 'g'."""
  new_rules = [x for x in g.rules if x != rule]
  refs = [x for x in g.rules if x.lhs == rule.rhs[0]]
  for ref in refs:
    new_rules.append(BuildUnitSkipRule(rule, ref))
  return Grammar(new_rules)


def Split(rule):
  """Splits a rule whose len(rhs) > 2 into shorter rules."""
  # if len(rule.rhs) <= 2:
  #   return [rule]
  rule_str = str(rule.lhs) + '__' + '_'.join(str(x) for x in rule.rhs)
  rule_name = '__SP_%s' % (rule_str) + '_%d'
  new_rules = [Rule(rule.lhs, [rule.rhs[0], NT(rule_name % 1)], weight=rule.weight, alias=rule.alias)]
  for i in xrange(1, len(rule.rhs) - 2):
    new_rules.append(
        Rule(NT(rule_name % i),
             [rule.rhs[i], NT(rule_name % (i + 1))], weight=0, alias='Split'))
  new_rules.append(Rule(NT(rule_name % (len(rule.rhs) - 2)), rule.rhs[-2:], weight=0, alias='Split'))
  return new_rules


def Term(g):
  """Applies the TERM rule on 'g' (see top comment)."""
  all_t = {x for rule in g.rules for x in rule.rhs if isinstance(x, T)}
  t_rules = {t: Rule(NT('__T_%s' % str(t)), [t], weight=0, alias='Term') for t in all_t}
  new_rules = []
  for rule in g.rules:
    if len(rule.rhs) > 1 and any(isinstance(x, T) for x in rule.rhs):
      new_rhs = [t_rules[x].lhs if isinstance(x, T) else x for x in rule.rhs]
      new_rules.append(Rule(rule.lhs, new_rhs, weight=rule.weight, alias=rule.alias))
      new_rules.extend(v for k, v in t_rules.iteritems() if k in rule.rhs)
    else:
      new_rules.append(rule)
  return Grammar(new_rules)


def Bin(g):
  """Applies the BIN rule to 'g' (see top comment)."""
  new_rules = []
  for rule in g.rules:
    if len(rule.rhs) > 2:
      new_rules.extend(Split(rule))
    else:
      new_rules.append(rule)
  return Grammar(new_rules)


def Unit(g):
  """Applies the UNIT rule to 'g' (see top comment)."""
  nt_unit_rule = GetAnyNtUnitRule(g)
  while nt_unit_rule:
    g = RemoveUnitRule(g, nt_unit_rule)
    nt_unit_rule = GetAnyNtUnitRule(g)
  return g


def ToCnf(g):
  """Creates a CNF grammar from a general context-free grammar 'g'."""
  g = Unit(Bin(Term(g)))
  return CnfWrapper(g)


def UnrollUnitSkipRule(lhs, orig_rhs, skipped_rules, children, weight, alias):
  if not skipped_rules:
    return RuleNode(Rule(lhs, orig_rhs, weight=weight, alias=alias), children, weight=weight)
  else:
    weight = weight - skipped_rules[0].weight
    return RuleNode(
        Rule(lhs, [skipped_rules[0].lhs], weight=weight, alias=alias), [
            UnrollUnitSkipRule(skipped_rules[0].lhs, orig_rhs,
                               skipped_rules[1:], children,
                               skipped_rules[0].weight, skipped_rules[0].alias)
        ], weight=weight)


def RevertCnf(node):
  """Reverts a parse tree (RuleNode) to its original non-CNF form (Node)."""
  if isinstance(node, T):
    return node
  # Reverts TERM rule.
  if node.rule.lhs.s.startswith('__T_'):
    return node.children[0]
  else:
    children = []
    reverted_children = [RevertCnf(x) for x in node.children]
    for child in reverted_children:
      # Reverts BIN rule.
      if isinstance(child, RuleNode) and child.rule.lhs.s.startswith('__SP_'):
        children.extend(child.children)
      else:
        children.append(child)
    # Reverts UNIT rule.
    if isinstance(node.rule, UnitSkipRule):
      return UnrollUnitSkipRule(node.rule.lhs, node.rule.rhs,
                                node.rule.skipped_rules, children,
                                node.rule.weight, node.rule.alias)
    else:
      return RuleNode(node.rule, children)