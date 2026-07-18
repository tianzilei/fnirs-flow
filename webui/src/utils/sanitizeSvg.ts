const BLOCKED_ELEMENT_NAMES = [
  'script',
  'foreignObject',
  'iframe',
  'object',
  'embed',
  'link',
  'meta',
  'style',
  'audio',
  'video',
  'canvas',
];

const BLOCKED_ELEMENT_PATTERN = new RegExp(
  `<\\s*(${BLOCKED_ELEMENT_NAMES.join('|')})\\b[\\s\\S]*?<\\s*\\/\\s*\\1\\s*>`,
  'gi',
);
const BLOCKED_SELF_CLOSING_PATTERN = new RegExp(
  `<\\s*(${BLOCKED_ELEMENT_NAMES.join('|')})\\b[^>]*\\/\\s*>`,
  'gi',
);
const EVENT_HANDLER_ATTRIBUTE_PATTERN = /\s+on[a-zA-Z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+)/g;
const STYLE_ATTRIBUTE_PATTERN = /\s+style\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+)/gi;
const URL_ATTRIBUTE_PATTERN = /\s+(href|xlink:href|src)\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+)/gi;
const UNSAFE_ATTRIBUTE_VALUE_PATTERN =
  /\s+[a-zA-Z_:.-]+\s*=\s*(?:"[^"]*(?:javascript:|data:|vbscript:)[^"]*"|'[^']*(?:javascript:|data:|vbscript:)[^']*'|[^\s"'=<>`]*(?:javascript:|data:|vbscript:)[^\s"'=<>`]*)/gi;

function stripPreamble(value: string): string {
  return value
    .replace(/^\uFEFF/, '')
    .replace(/^<\?xml[\s\S]*?\?>\s*/i, '')
    .replace(/<!doctype[\s\S]*?>/gi, '')
    .trim();
}

function unquoteAttributeValue(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function sanitizeUrlAttributes(value: string): string {
  return value.replace(URL_ATTRIBUTE_PATTERN, (match, _name: string, rawValue: string) => {
    const url = unquoteAttributeValue(rawValue).trim().toLowerCase();
    return url.startsWith('#') ? match : '';
  });
}

export function sanitizeSvg(svg: string): string {
  const trimmed = stripPreamble(svg);
  if (!/^<svg(?:\s|>)/i.test(trimmed) || !/<\/svg>\s*$/i.test(trimmed)) {
    return '';
  }

  return trimmed
    .replace(BLOCKED_ELEMENT_PATTERN, '')
    .replace(BLOCKED_SELF_CLOSING_PATTERN, '')
    .replace(EVENT_HANDLER_ATTRIBUTE_PATTERN, '')
    .replace(STYLE_ATTRIBUTE_PATTERN, '')
    .replace(UNSAFE_ATTRIBUTE_VALUE_PATTERN, '')
    .replace(URL_ATTRIBUTE_PATTERN, (match) => sanitizeUrlAttributes(match));
}
