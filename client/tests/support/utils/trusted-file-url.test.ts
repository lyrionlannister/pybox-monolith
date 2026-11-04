import { describe, expect, it } from "vitest";
import { isTrustedFileUrl } from "@/support/utils/trusted-file-url";

const API = "https://api.pybox.test/api/v1";

describe("isTrustedFileUrl", () => {
  it("acepta URLs de la API", () => {
    expect(isTrustedFileUrl("https://api.pybox.test/api/v1/organizations/x/documents/y/content", API)).toBe(true);
  });

  it("acepta rutas relativas de la propia app", () => {
    expect(isTrustedFileUrl("/files/x.pdf", API)).toBe(true);
  });

  it("rechaza otros orígenes", () => {
    expect(isTrustedFileUrl("https://evil.example.com/login", API)).toBe(false);
  });

  it("rechaza esquemas no http", () => {
    expect(isTrustedFileUrl("javascript:alert(1)", API)).toBe(false);
    expect(isTrustedFileUrl("data:text/html,<script>x</script>", API)).toBe(false);
  });

  it("rechaza vacío", () => {
    expect(isTrustedFileUrl("", API)).toBe(false);
  });
});
