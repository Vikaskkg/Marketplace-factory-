import "@testing-library/jest-dom/vitest";

// jsdom does not implement <dialog> methods; a small stand-in is enough for these tests.
const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
if (typeof proto.showModal !== "function") {
  proto.showModal = function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
  proto.close = function (this: HTMLDialogElement) { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); };
}
