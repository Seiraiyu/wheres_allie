import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import App from "./App";

test("left rail links every page and / redirects to Live", () => {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
  const nav = screen.getByRole("navigation", { name: "Pages" });
  const labels = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("title"));
  expect(labels).toEqual(["Live", "History", "Plan", "Nodes", "Calibrate", "Data", "Setup"]);
  expect(screen.getByRole("heading", { name: "Live" })).toBeTruthy();
});
