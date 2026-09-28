/**
 * SIH26150 — Public Website Main Script
 * Handles navigation, filter tabs, copy-to-clipboard, accordions, and interactions
 */

document.addEventListener('DOMContentLoaded', function () {
  // Mobile Nav Toggle
  const mobileToggle = document.getElementById('mobileNavToggle');
  const navMenu = document.getElementById('navMenu');

  if (mobileToggle && navMenu) {
    mobileToggle.addEventListener('click', function () {
      const isVisible = navMenu.style.display === 'flex';
      navMenu.style.display = isVisible ? 'none' : 'flex';
      if (!isVisible) {
        navMenu.style.flexDirection = 'column';
        navMenu.style.position = 'absolute';
        navMenu.style.top = '74px';
        navMenu.style.left = '0';
        navMenu.style.width = '100%';
        navMenu.style.background = '#090e17';
        navMenu.style.padding = '20px 24px';
        navMenu.style.borderBottom = '1px solid rgba(56, 189, 248, 0.2)';
        navMenu.style.gap = '16px';
      }
    });
  }

  // Smooth Scrolling & Active State
  const navLinks = document.querySelectorAll('.nav-link');
  const sections = document.querySelectorAll('section[id]');

  window.addEventListener('scroll', function () {
    const scrollY = window.pageYOffset;

    sections.forEach(function (current) {
      const sectionHeight = current.offsetHeight;
      const sectionTop = current.offsetTop - 100;
      const sectionId = current.getAttribute('id');

      if (scrollY > sectionTop && scrollY <= sectionTop + sectionHeight) {
        navLinks.forEach(function (link) {
          link.classList.remove('active');
          if (link.getAttribute('href') === '#' + sectionId) {
            link.classList.add('active');
          }
        });
      }
    });
  });

  // Copy SHA-256 Checksum to Clipboard
  const copyBtn = document.getElementById('copyHashBtn');
  const hashText = document.getElementById('installerHashVal');

  if (copyBtn && hashText) {
    copyBtn.addEventListener('click', function () {
      const textToCopy = hashText.textContent.trim();
      navigator.clipboard.writeText(textToCopy).then(
        function () {
          const original = copyBtn.textContent;
          copyBtn.textContent = 'COPIED TO CLIPBOARD!';
          copyBtn.style.color = '#10b981';
          setTimeout(function () {
            copyBtn.textContent = original;
            copyBtn.style.color = '';
          }, 2500);
        },
        function () {
          // Fallback selection
          const range = document.createRange();
          range.selectNodeContents(hashText);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
        }
      );
    });
  }

  // Supported Vendors Category Filtering
  const filterBtns = document.querySelectorAll('.filter-btn');
  const vendorCards = document.querySelectorAll('.vendor-card');

  filterBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      filterBtns.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');

      const filter = btn.getAttribute('data-filter');

      vendorCards.forEach(function (card) {
        if (filter === 'all' || card.getAttribute('data-status') === filter) {
          card.style.display = 'flex';
        } else {
          card.style.display = 'none';
        }
      });
    });
  });

  // Track / Highlight Windows Download Action
  const downloadBtns = document.querySelectorAll('a[download]');
  downloadBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      console.log('[SIH26150] Direct Windows Installer download requested: SIH-Forensic-Tool-Setup.exe');
    });
  });
});
