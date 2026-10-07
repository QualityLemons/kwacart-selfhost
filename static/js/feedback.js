(function () {
  "use strict";
  function key(el) { return ["kwacart_feedback_prompt", el.dataset.source, el.dataset.toolSlug, el.dataset.interactionMode].join(":"); }
  document.querySelectorAll("[data-feedback-prompt]").forEach(function (prompt) {
    var storageKey = key(prompt);
    try { if (localStorage.getItem(storageKey)) prompt.hidden = true; } catch (_) {}
    var dismiss = prompt.querySelector("[data-feedback-dismiss]");
    if (dismiss) dismiss.addEventListener("click", function () {
      try { localStorage.setItem(storageKey, "dismissed"); } catch (_) {}
      prompt.hidden = true;
    });
    var form = prompt.querySelector("form");
    if (form) form.addEventListener("submit", function () {
      try { localStorage.setItem(storageKey, "submitted"); } catch (_) {}
    });
  });

  document.querySelectorAll("[data-feedback-form]").forEach(function (form) {
    var type = form.querySelector("#id_feedback_type");
    var rating = form.querySelector("#id_rating");
    var title = form.querySelector("#id_title");
    var description = form.querySelector("#id_description");
    if (!type || !rating || !title || !description) return;

    var ratingRow = rating.closest("[data-feedback-rating-field]");
    var titleRow = title.closest("[data-feedback-title-field]");
    var descriptionRow = description.closest("[data-feedback-description-field]");
    if (!ratingRow || !titleRow || !descriptionRow) return;

    function updateFields() {
      var isRating = type.value === "rating";
      ratingRow.hidden = !isRating;
      titleRow.hidden = isRating;
      descriptionRow.hidden = isRating;
      rating.required = isRating;
      title.required = !isRating;
      description.required = !isRating;
    }

    type.addEventListener("change", updateFields);
    updateFields();
  });
}());