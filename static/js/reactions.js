"use strict";

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!form.matches("[data-reaction-form]") || !event.submitter) return;
  event.preventDefault();
  const group = form.closest("[data-reaction-group]");
  if (group.dataset.busy === "true") return;
  const body = new FormData(form);
  body.set("reaction", event.submitter.value);
  const groups = [...document.querySelectorAll("[data-reaction-group]")]
    .filter((entry) => entry.dataset.newsId === group.dataset.newsId);
  const feedback = group.querySelector(".news-reactions-feedback");
  feedback.textContent = "";
  for (const entry of groups) {
    entry.dataset.busy = "true";
    entry.setAttribute("aria-busy", "true");
    entry.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  }
  try {
    const response = await fetch(form.action, {
      method: "POST", body, credentials: "same-origin", headers: { Accept: "application/json" },
    });
    if (!response.headers.get("Content-Type")?.includes("application/json")) {
      throw new Error("Не удалось сохранить реакцию. Обновите страницу и попробуйте ещё раз.");
    }
    const data = await response.json();
    if (response.status === 401 && data.login_url) {
      window.location.assign(data.login_url);
      return;
    }
    if (!response.ok) throw new Error(data.message || "Не удалось сохранить реакцию.");
    for (const entry of groups) {
      for (const button of entry.querySelectorAll("[data-reaction]")) {
        const selected = data.selected === button.dataset.reaction;
        const count = data.counts[button.dataset.reaction];
        button.classList.toggle("is-selected", selected);
        button.setAttribute("aria-pressed", String(selected));
        button.setAttribute("aria-label", `${button.dataset.label}: ${count}${selected ? ". Убрать реакцию" : ""}`);
        button.title = selected ? "Убрать реакцию" : button.dataset.label;
        button.querySelector(".news-reaction-count").textContent = count;
      }
    }
    feedback.textContent = data.selected ? "Реакция сохранена." : "Реакция убрана.";
  } catch (error) {
    feedback.textContent = error.message || "Не удалось сохранить реакцию. Попробуйте ещё раз.";
  } finally {
    for (const entry of groups) {
      delete entry.dataset.busy;
      entry.removeAttribute("aria-busy");
      entry.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    }
  }
});
