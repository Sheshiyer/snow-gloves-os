```markdown
# snow-gloves-os Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches you the core development patterns and conventions used in the `snow-gloves-os` Python codebase. You'll learn how to structure files, write imports and exports, follow commit message conventions, and understand the project's approach to testing. This guide ensures consistency and efficiency for contributors.

## Coding Conventions

### File Naming
- Use **snake_case** for all file and module names.
  - Example: `user_profile.py`, `data_loader.py`

### Import Style
- Use **relative imports** within the package.
  - Example:
    ```python
    from .utils import parse_config
    from ..models.user import User
    ```

### Export Style
- Use **named exports** (explicitly define what is exported).
  - Example:
    ```python
    __all__ = ['User', 'parse_config']
    ```

### Commit Messages
- Follow the **conventional commits** style.
- Use the `feat` prefix for new features.
- Keep commit messages concise (average 44 characters).
  - Example:
    ```
    feat: add user authentication module
    ```

## Workflows

### Feature Development
**Trigger:** When adding a new feature  
**Command:** `/feature-dev`

1. Create a new branch for your feature.
2. Implement the feature using snake_case for files and relative imports.
3. Add or update named exports as needed.
4. Write or update tests (see Testing Patterns).
5. Commit using the `feat` prefix and a concise message.
6. Open a pull request for review.

### Code Importing
**Trigger:** When importing modules within the project  
**Command:** `/import-module`

1. Use relative imports for all internal modules.
   - Example:
     ```python
     from .helpers import calculate_score
     ```

### Commit Workflow
**Trigger:** When committing code  
**Command:** `/commit`

1. Write a commit message using the `feat` prefix for features.
2. Keep the message concise and descriptive.
   - Example:
     ```
     feat: implement data validation for inputs
     ```

## Testing Patterns

- Test files are written with the `.test.ts` pattern (TypeScript), though the main codebase is Python.
- The testing framework is **unknown**; check existing `.test.ts` files for structure.
- Place test files alongside or near the modules they test.
- Example test file name: `user_profile.test.ts`

## Commands
| Command         | Purpose                                   |
|-----------------|-------------------------------------------|
| /feature-dev    | Start a new feature development workflow   |
| /import-module  | Import a module using relative imports     |
| /commit         | Commit code following conventions          |
```
