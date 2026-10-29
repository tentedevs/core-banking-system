import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { App } from "./App";

it("renders the independent CBS application", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Core Banking System" })).toBeTruthy();
});
