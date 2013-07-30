from unipycation import Term, Var, CoreEngine, PrologError

class InstantiationError(Exception): pass

def build_prolog_list(elems):
    """ Converts a Python list into a cons chain """
    # Iterative, to avoid list slicing (linear in list size)
    n_elems = len(elems)
    e = "[]"
    for i in xrange(n_elems - 1, -1, -1):
        e = Term(".", [elems[i], e])

    return e

def unpack_prolog_list(obj):
    assert obj.name == "."
    curr = obj
    result = []
    while True:
        if isinstance(curr, Var): # the rest of the list is unknown
            raise InstantiationError("The tail of a list was undefined")
        if curr == "[]": # end of list
            return result
        if not isinstance(curr, Term) or not curr.name == ".":
            return obj # malformed list, just return it unconverted
        result.append(curr.args[0])
        curr = curr.args[1]

class Engine(object):
    """ A wrapper around unipycation.CoreEngine. """
    def __init__(self, db_str):
        self.engine = CoreEngine(db_str)
        self.db = Database(self)
        self.terms = TermPool()

class SolutionIterator(object):
    """ A wrapper around unipycation.CoreSolutionIterator. """
    def __init__(self, it, vs):
        self.it = it
        self.vs = vs # indicates order of returned solutions

    def __iter__(self): return self

    def next(self):
        sol = self.it.next()
        return Predicate._make_result_tuple(sol, self.vs)

class Predicate(object):
    """ Represents a "callable" prolog predicate """

    def __init__(self, engine, name):
        self.engine = engine
        self.many_solutions = False
        self.name = name

    @staticmethod
    def _convert_to_prolog(e):
        if isinstance(e, list):
            return build_prolog_list(e)
        else:
            return e

    @staticmethod
    def _back_to_py(e):
        if e == "[]":
            return []
        if (not isinstance(e, Term)):
            return e
        elif e.name == ".":
            return unpack_prolog_list(e)
        else:
            # is a Term
            return e

    @staticmethod
    def _make_result_tuple(sol, variables):
        return tuple([ Predicate._back_to_py(sol[v]) for v in variables ])

    def __call__(self, *args):
        term_args = []
        vs = []
        for e in args:
            if e is None:
                var = Var()
                term_args.append(var)
                vs.append(var)
            else:
                term_args.append(self._convert_to_prolog(e))
        t = Term(self.name, term_args)

        if self.many_solutions:
            it = self.engine.engine.query_iter(t, vs)
            return SolutionIterator(it, vs)
        else:
            sol = self.engine.engine.query_single(t, vs)

            if sol is None:
                return None # contradiction
            else:
                return Predicate._make_result_tuple(sol, vs)
    
class Database(object):
    """ A class that represents the predicates exposed by a prolog engine """

    def __init__(self, engine):
        self.engine = engine

    def __getattr__(self, name):
        """ Predicates are called by db.name and are resolved dynamically """
        pred = Predicate(self.engine, name)
        setattr(self, name, pred)
        return pred

class TermPool(object):
    """ Represents the term pool, some magic to make term creation prettier """

    @staticmethod
    def _magic_convert(name, args):
        """ For now this is where pylists become cons chains in term args """

        new_args = []
        for a in args:
            new_args.append(Predicate._convert_to_prolog(a))

        return Term(name, new_args)

    def __getattr__(self, name):
        # Note that we cant memoise these due to the args being variable
        return lambda *args : TermPool._magic_convert(name, args)
