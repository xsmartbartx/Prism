"""Binding — declarative source-to-dataset compilation.

Provides:
  - SourceBinding: the declarative binding document (imported from schemas)
  - BindingCompiler: transforms a binding into an immutable ImportPlan
  - BindingRegistry: content-addressed store of published binding versions
"""