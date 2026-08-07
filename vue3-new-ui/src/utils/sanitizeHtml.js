const ALLOWED_TAGS = new Set(["A", "B", "BLOCKQUOTE", "BR", "CODE", "EM", "H1", "H2", "H3", "I", "LI", "OL", "P", "PRE", "STRONG", "UL"]);
const ALLOWED_ATTRIBUTES = new Set(["href", "target", "rel"]);

export function sanitizeHtml(value = "") {
  if (typeof document === "undefined") return String(value).replace(/<[^>]*>/g, "");
  const template = document.createElement("template");
  template.innerHTML = String(value);
  const elements = template.content.querySelectorAll("*");
  elements.forEach((element) => {
    if (!ALLOWED_TAGS.has(element.tagName)) {
      element.replaceWith(document.createTextNode(element.textContent || ""));
      return;
    }
    [...element.attributes].forEach((attribute) => {
      const name = attribute.name.toLowerCase();
      const valueText = attribute.value.trim().toLowerCase();
      const unsafeUrl = (name === "href" && !/^(https?:|mailto:|#)/i.test(attribute.value)) || valueText.startsWith("javascript:");
      if (!ALLOWED_ATTRIBUTES.has(name) || unsafeUrl || name.startsWith("on")) element.removeAttribute(attribute.name);
    });
    if (element.tagName === "A") {
      element.setAttribute("target", "_blank");
      element.setAttribute("rel", "noopener noreferrer");
    }
  });
  return template.innerHTML;
}
