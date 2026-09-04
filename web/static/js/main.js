document.addEventListener("DOMContentLoaded", () => {
  // Subtle scanline flicker on brand
  const brand = document.querySelector(".brand");
  if (brand) {
    setInterval(() => {
      brand.style.opacity = Math.random() > 0.92 ? "0.75" : "1";
    }, 120);
  }
});
