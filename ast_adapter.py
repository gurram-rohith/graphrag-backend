# ast_adapter.py
from tree_sitter import Parser, Language, Query, QueryCursor
import tree_sitter_javascript as ts_js
import tree_sitter_python as ts_python
import tree_sitter_java as ts_java
import tree_sitter_c as ts_c
import tree_sitter_cpp as ts_cpp

# 1. Configuration Dictionary
# This maps file extensions to their specific language bindings and syntax queries.
LANGUAGE_MAP = {
    ".js": {
        "lang": ts_js.language(),
        "query": "(call_expression function: (identifier) @call_name)",
        "func_types": ["function_declaration", "arrow_function", "function"]
    },
    ".py": {
        "lang": ts_python.language(),
        "query": "(call function: (identifier) @call_name)",
        "func_types": ["function_definition"]
    },
    ".java": {
        "lang": ts_java.language(),
        "query": "(method_invocation name: (identifier) @call_name)",
        "func_types": ["method_declaration"]
    },
    ".c": {
        "lang": ts_c.language(),
        "query": "(call_expression function: (identifier) @call_name)",
        "func_types": ["function_definition"]
    },
    ".cpp": {
        "lang": ts_cpp.language(),
        "query": "(call_expression function: (identifier) @call_name)",
        "func_types": ["function_definition"]
    }
}

class UniversalParser:
    def __init__(self, ext):
        if ext not in LANGUAGE_MAP:
            raise ValueError(f"Unsupported extension: {ext}")
            
        config = LANGUAGE_MAP[ext]
        self.language = Language(config["lang"])
        self.parser = Parser(self.language)
        self.query_string = config["query"]
        self.func_types = config["func_types"]

    def _get_parent_func_name(self, node):
        """Generic parent traversal using the configured function types."""
        current = node.parent
        while current:
            if current.type in self.func_types:
                name_node = current.child_by_field_name("name")
                if name_node:
                    return name_node.text.decode("utf8")
            current = current.parent
        return "global"

    def extract_calls(self, source_code):
        """
        Returns a clean Python list of tuples: [('caller_func', 'callee_func')]
        No tree-sitter objects leak out of this function.
        """
        tree = self.parser.parse(bytes(source_code, "utf8"))
        query = Query(self.language, self.query_string)
        cursor = QueryCursor(query)
        results = cursor.captures(tree.root_node)
        
        extracted_calls = []
        
        if isinstance(results, dict):
            nodes_to_process = results.get("call_name", [])
        else:
            nodes_to_process = [item[0] for item in results if isinstance(item, tuple) and item[1] == "call_name"]

        if not isinstance(nodes_to_process, list):
            nodes_to_process = [nodes_to_process]

        for node in nodes_to_process:
            if not node: continue
            call_name = node.text.decode("utf8")
            parent_func = self._get_parent_func_name(node)
            extracted_calls.append((parent_func, call_name))
            
        return extracted_calls