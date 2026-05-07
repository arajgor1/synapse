/**
 * Critical-scope matcher.
 *
 * A `criticalScopes` list is a set of glob patterns (e.g. `billing.*`,
 * `prod.deploy.*`). When any of them match a scope on a CONFLICT-bearing
 * intention, the system forces `MergePolicy.abort` regardless of the
 * configured policy. Hard guardrail for production-sensitive scopes.
 *
 * Ported from `sdk-python/synapse/policies/critical.py`. We hand-roll a
 * fnmatch-equivalent (no extra deps) since Python `fnmatch` semantics are
 * narrow: `*` matches any sequence, `?` matches one char, `[seq]` matches
 * a char in the set. That's sufficient for the patterns Synapse ships
 * (`billing.*`, `prod.deploy.*`, etc.).
 */

/** Normalize the user's input — strip whitespace, drop empties. */
export function normalizeCriticalScopes(
  specs: Iterable<string> | null | undefined,
): string[] {
  if (!specs) return [];
  const out: string[] = [];
  for (const raw of specs) {
    const s = (raw || "").trim();
    if (s) out.push(s);
  }
  return out;
}

/**
 * Translate an fnmatch glob into an anchored RegExp.
 *
 * Matches Python's `fnmatch.fnmatchcase` semantics: case-sensitive,
 * `*` matches anything (including dots), `?` matches one char, `[abc]`
 * char class. Other regex meta-characters are escaped.
 */
function fnmatchToRegex(pattern: string): RegExp {
  let out = "^";
  let i = 0;
  while (i < pattern.length) {
    const c = pattern[i]!;
    if (c === "*") {
      out += ".*";
      i++;
    } else if (c === "?") {
      out += ".";
      i++;
    } else if (c === "[") {
      // Find matching ]
      let j = i + 1;
      if (j < pattern.length && pattern[j] === "!") j++;
      if (j < pattern.length && pattern[j] === "]") j++;
      while (j < pattern.length && pattern[j] !== "]") j++;
      if (j >= pattern.length) {
        // No closing bracket — treat literal
        out += "\\[";
        i++;
      } else {
        let cls = pattern.slice(i + 1, j);
        if (cls.startsWith("!")) cls = "^" + cls.slice(1);
        // Escape backslash inside class
        cls = cls.replace(/\\/g, "\\\\");
        out += "[" + cls + "]";
        i = j + 1;
      }
    } else {
      // Escape regex metacharacters
      if (/[.+^${}()|\\]/.test(c)) out += "\\" + c;
      else out += c;
      i++;
    }
  }
  out += "$";
  return new RegExp(out);
}

/**
 * Return the first matched pattern, or null.
 *
 * Strips the modifier suffix (`:r` / `:w`) before matching so a pattern
 * like `billing.*` matches both `billing.charge:w` and `billing.charge:r`.
 */
export function criticalScopeMatch(
  intentionScopes: Iterable<string>,
  criticalPatterns: Iterable<string>,
): string | null {
  const patterns = Array.from(criticalPatterns);
  for (const scope of intentionScopes) {
    const base = scope.includes(":") ? scope.split(":")[0]! : scope;
    for (const pattern of patterns) {
      const patBase = pattern.includes(":")
        ? pattern.split(":")[0]!
        : pattern;
      if (fnmatchToRegex(patBase).test(base)) {
        return pattern;
      }
    }
  }
  return null;
}
