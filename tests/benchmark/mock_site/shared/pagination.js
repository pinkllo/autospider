document.addEventListener("DOMContentLoaded", () => {
  const pagination = document.querySelector(".pagination");
  if (!pagination) {
    return;
  }
  pagination.setAttribute("data-pagination-ready", "true");
});
