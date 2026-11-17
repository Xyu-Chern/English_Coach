"""The tools both systems use on a draft. Each call is one budgeted, traced step.

    tool                 file          baseline uses          agent action
    search, search_slot  search.py     a search per new       search
                                       expression
    select               select.py     a selection per round  (the agent picks through repick/replace)
    change_slot          change.py     -                      repick, replace
    validate, assemble   assemble.py   after each round       after each turn
                                       and at the end         and at the end

The baseline calls them in a fixed order (systems/baseline.py); the agent's reply lists actions
that code runs with them (systems/agent.py). The corpus itself is searched through the
session (session.search), which wraps translation_agent_demo/tools/search_corpus.py.
"""

from .assemble import assemble, new_log, validate
from .change import ReplaceAction, RepickAction, as_candidate, change_slot
from .search import SearchAction, identical_search, search, search_slot
from .select import select

__all__ = ["search", "search_slot", "identical_search", "select", "change_slot", "as_candidate", "validate",
           "new_log", "assemble", "SearchAction", "RepickAction", "ReplaceAction"]
