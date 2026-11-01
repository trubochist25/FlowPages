(function () {
  'use strict';

  var instanceNumber = 0;

  function Autocomplete(root) {
    this.root = root;
    this.input = root.querySelector('input[type="search"], input[type="text"]');
    this.endpoint = root.getAttribute('data-suggest-url') || '';
    this.minimumLength = parseInt(root.getAttribute('data-min-length'), 10) || 2;
    this.limit = parseInt(root.getAttribute('data-limit'), 10) || 8;
    this.items = [];
    this.activeIndex = -1;
    this.timer = null;
    this.request = null;
    this.requestNumber = 0;
    this.list = null;

    if (!this.input || !this.endpoint) return;

    this.createList();
    this.bind();
  }

  Autocomplete.prototype.createList = function () {
    instanceNumber += 1;
    this.list = document.createElement('ul');
    this.list.id = 'fp-autocomplete-' + instanceNumber;
    this.list.className = 'fp-autocomplete__list';
    this.list.setAttribute('role', 'listbox');
    this.list.hidden = true;

    this.root.classList.add('fp-autocomplete');
    this.root.appendChild(this.list);
    this.input.setAttribute('role', 'combobox');
    this.input.setAttribute('aria-autocomplete', 'list');
    this.input.setAttribute('aria-controls', this.list.id);
    this.input.setAttribute('aria-expanded', 'false');
  };

  Autocomplete.prototype.bind = function () {
    var self = this;

    this.input.addEventListener('input', function () {
      self.schedule();
    });
    this.input.addEventListener('keydown', function (event) {
      self.onKeydown(event);
    }, true);
    this.input.addEventListener('focus', function () {
      if (self.items.length && self.input.value.trim().length >= self.minimumLength) {
        self.open();
      }
    });
    this.input.addEventListener('blur', function () {
      window.setTimeout(function () { self.close(); }, 120);
    });
    this.list.addEventListener('mousedown', function (event) {
      var option = event.target.closest('[data-suggestion-index]');
      if (!option) return;
      event.preventDefault();
      self.choose(parseInt(option.getAttribute('data-suggestion-index'), 10));
    });
  };

  Autocomplete.prototype.schedule = function () {
    var self = this;
    window.clearTimeout(this.timer);
    this.cancelRequest();
    this.close();

    if (this.input.value.trim().length < this.minimumLength) {
      this.items = [];
      this.render();
      return;
    }

    this.timer = window.setTimeout(function () { self.load(); }, 250);
  };

  Autocomplete.prototype.load = function () {
    var self = this;
    var query = this.input.value.trim();
    var requestNumber = ++this.requestNumber;
    var separator = this.endpoint.indexOf('?') === -1 ? '?' : '&';
    var url = this.endpoint + separator + 'q=' + encodeURIComponent(query) + '&limit=' + encodeURIComponent(this.limit);
    var request = new XMLHttpRequest();

    this.request = request;
    request.open('GET', url, true);
    request.setRequestHeader('Accept', 'application/json');
    request.onreadystatechange = function () {
      if (request.readyState !== 4 || requestNumber !== self.requestNumber) return;

      if (request.status >= 200 && request.status < 300) {
        try {
          var response = JSON.parse(request.responseText);
          self.items = Array.isArray(response.suggestions)
            ? response.suggestions.filter(function (item) {
              return item && typeof item.label === 'string' && typeof item.value === 'string';
            })
            : [];
        } catch (error) {
          self.items = [];
        }
      } else {
        self.items = [];
      }

      self.activeIndex = -1;
      self.render();
      if (self.items.length && self.input === document.activeElement) self.open();
      if (self.request === request) self.request = null;
    };
    request.send();
  };

  Autocomplete.prototype.cancelRequest = function () {
    this.requestNumber += 1;
    if (this.request && this.request.readyState !== 4) this.request.abort();
    this.request = null;
  };

  Autocomplete.prototype.render = function () {
    var self = this;
    this.list.textContent = '';

    this.items.forEach(function (item, index) {
      var option = document.createElement('li');
      option.id = self.list.id + '-option-' + index;
      option.className = 'fp-autocomplete__option';
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', 'false');
      option.setAttribute('data-suggestion-index', index);

      if (item.type === 'book' && typeof item.image === 'string' && item.image) {
        option.classList.add('fp-autocomplete__option--book');
        var cover = document.createElement('img');
        cover.className = 'fp-autocomplete__cover';
        cover.src = item.image;
        cover.alt = '';
        cover.setAttribute('aria-hidden', 'true');
        cover.setAttribute('loading', 'lazy');
        option.appendChild(cover);
      }

      var label = document.createElement('span');
      label.className = 'fp-autocomplete__label';
      label.textContent = item.label;
      option.appendChild(label);
      self.list.appendChild(option);
    });
  };

  Autocomplete.prototype.onKeydown = function (event) {
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && this.items.length) {
      event.preventDefault();
      if (this.list.hidden) this.open();
      var direction = event.key === 'ArrowDown' ? 1 : -1;
      var next = this.activeIndex + direction;
      if (next < 0) next = this.items.length - 1;
      if (next >= this.items.length) next = 0;
      this.activate(next);
      return;
    }

    if (event.key === 'Tab' && !this.list.hidden && this.items.length) {
      event.preventDefault();
      this.complete(this.activeIndex >= 0 ? this.activeIndex : 0);
      return;
    }

    if (event.key === 'Enter' && !this.list.hidden && this.activeIndex >= 0) {
      event.preventDefault();
      event.stopImmediatePropagation();
      this.choose(this.activeIndex);
      return;
    }

    if (event.key === 'Escape' && !this.list.hidden) {
      event.preventDefault();
      this.close();
    }
  };

  Autocomplete.prototype.activate = function (index) {
    var options = this.list.querySelectorAll('[data-suggestion-index]');
    Array.prototype.forEach.call(options, function (option) {
      option.classList.remove('is-active');
      option.setAttribute('aria-selected', 'false');
    });

    this.activeIndex = index;
    if (!options[index]) return;
    options[index].classList.add('is-active');
    options[index].setAttribute('aria-selected', 'true');
    options[index].scrollIntoView({ block: 'nearest' });
    this.input.setAttribute('aria-activedescendant', options[index].id);
  };

  Autocomplete.prototype.complete = function (index) {
    if (!this.items[index]) return;
    this.input.value = this.items[index].value;
    this.input.dispatchEvent(new Event('change', { bubbles: true }));
    this.close();
  };

  Autocomplete.prototype.choose = function (index) {
    var item = this.items[index];
    if (!item) return;
    this.input.value = item.value;
    this.close();

    if (item.url) {
      window.location.assign(item.type !== 'book' && typeof flowpagesSearchUrl === 'function'
        ? flowpagesSearchUrl(item.url, item.value)
        : item.url);
      return;
    }

    var searchUrl = this.root.getAttribute('data-search-url');
    if (searchUrl) {
      var separator = searchUrl.indexOf('?') === -1 ? '?' : '&';
      window.location.assign(typeof flowpagesSearchUrl === 'function'
        ? flowpagesSearchUrl(searchUrl, item.value)
        : searchUrl + separator + 'search=' + encodeURIComponent(item.value));
    }
  };

  Autocomplete.prototype.open = function () {
    if (!this.items.length) return;
    this.list.hidden = false;
    this.input.setAttribute('aria-expanded', 'true');
  };

  Autocomplete.prototype.close = function () {
    this.list.hidden = true;
    this.activeIndex = -1;
    this.input.setAttribute('aria-expanded', 'false');
    this.input.removeAttribute('aria-activedescendant');
  };

  function initialise() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-fp-autocomplete]'), function (root) {
      if (root.getAttribute('data-fp-autocomplete-ready') === 'true') return;
      root.setAttribute('data-fp-autocomplete-ready', 'true');
      new Autocomplete(root);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialise);
  } else {
    initialise();
  }

  window.FlowPagesAutocomplete = { initialise: initialise };
}());
