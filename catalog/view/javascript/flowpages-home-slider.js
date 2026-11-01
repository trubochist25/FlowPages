(function () {
  'use strict';

  var sliders = document.querySelectorAll('[data-fp-slider]');

  Array.prototype.forEach.call(sliders, function (slider) {
    var collection = slider.closest('.fp-collection');
    var track = slider.querySelector('[data-fp-slider-track]');
    var pages = slider.querySelectorAll('[data-fp-slider-page]');
    var previous = collection.querySelector('[data-fp-slider-prev]');
    var next = collection.querySelector('[data-fp-slider-next]');
    var current = collection.querySelector('[data-fp-slider-current]');
    var position = collection.querySelector('[data-fp-slider-position]');
    var pageIndex = 0;
    var visualIndex = 1;
    var isMoving = false;
    var resetTimer = null;

    if (!track || !pages.length || !previous || !next || !current || !position) {
      return;
    }

    var firstClone = pages[0].cloneNode(true);
    var lastClone = pages[pages.length - 1].cloneNode(true);

    firstClone.removeAttribute('data-fp-slider-page');
    lastClone.removeAttribute('data-fp-slider-page');
    firstClone.setAttribute('data-fp-slider-clone', 'first');
    lastClone.setAttribute('data-fp-slider-clone', 'last');
    firstClone.setAttribute('aria-hidden', 'true');
    lastClone.setAttribute('aria-hidden', 'true');
    firstClone.setAttribute('inert', '');
    lastClone.setAttribute('inert', '');
    track.insertBefore(lastClone, track.firstChild);
    track.appendChild(firstClone);

    function setTrackPosition(animate) {
      track.style.transition = animate ? '' : 'none';
      track.style.transform = 'translate3d(' + (-visualIndex * 100) + '%, 0, 0)';

      if (!animate) {
        // Commit the clone-to-real-page jump while transitions are disabled.
        // Without this reflow, the browser may batch the jump with the restored
        // transition and visibly animate across all three pages backwards.
        track.offsetWidth;
      }
    }

    function updateSliderState() {
      current.textContent = String(pageIndex + 1).padStart(2, '0');
      position.setAttribute('aria-label', 'Порция ' + (pageIndex + 1) + ' из ' + pages.length);

      Array.prototype.forEach.call(pages, function (page, index) {
        var isCurrent = index === pageIndex;
        page.setAttribute('aria-hidden', isCurrent ? 'false' : 'true');

        if (isCurrent) {
          page.removeAttribute('inert');
        } else {
          page.setAttribute('inert', '');
        }
      });
    }

    function finishMove() {
      if (!isMoving) {
        return;
      }

      if (visualIndex === 0) {
        visualIndex = pages.length;
        setTrackPosition(false);
      } else if (visualIndex === pages.length + 1) {
        visualIndex = 1;
        setTrackPosition(false);
      }

      isMoving = false;
      window.clearTimeout(resetTimer);
      track.style.transition = '';
    }

    function moveSlider(direction) {
      if (isMoving) {
        return;
      }

      isMoving = true;
      pageIndex = (pageIndex + direction + pages.length) % pages.length;
      visualIndex += direction;
      setTrackPosition(true);
      updateSliderState();
      resetTimer = window.setTimeout(finishMove, 560);
    }

    track.addEventListener('transitionend', function (event) {
      if (event.propertyName === 'transform') {
        finishMove();
      }
    });

    previous.addEventListener('click', function () {
      moveSlider(-1);
    });

    next.addEventListener('click', function () {
      moveSlider(1);
    });

    setTrackPosition(false);
    updateSliderState();
    window.requestAnimationFrame(function () {
      track.style.transition = '';
    });
  });
}());
