(function () {
  'use strict';

  function initAlchemy() {
    var root = document.getElementById('fp-alchemy');
    if (!root || !window.fetch) {
      return;
    }

    var query = document.getElementById('fp-alchemy-query');
    var counter = document.getElementById('fp-alchemy-counter');
    var analyzeForm = document.getElementById('fp-alchemy-analyze-form');
    var analyzeButton = document.getElementById('fp-alchemy-analyze');
    var mixButton = document.getElementById('fp-alchemy-mix');
    var status = document.getElementById('fp-alchemy-status');
    var recipe = document.getElementById('fp-alchemy-recipe');
    var recipeEmpty = document.getElementById('fp-alchemy-recipe-empty');
    var analysisNotices = document.getElementById('fp-alchemy-analysis-notices');
    var resultNotices = document.getElementById('fp-alchemy-result-notices');
    var results = document.getElementById('fp-alchemy-results');
    var resultsEmpty = document.getElementById('fp-alchemy-results-empty');
    var resultMeta = document.getElementById('fp-alchemy-result-meta');
    var resultsStage = document.getElementById('fp-alchemy-results-stage');
    var output = document.getElementById('fp-alchemy-output');
    var ritual = document.getElementById('fp-alchemy-ritual');
    var ritualTokens = document.getElementById('fp-alchemy-ritual-tokens');
    var ritualTitle = document.getElementById('fp-alchemy-ritual-title');
    var positiveList = document.getElementById('fp-positive-list');
    var negativeList = document.getElementById('fp-negative-list');
    var anchorList = document.getElementById('fp-anchor-list');
    var anchorQuery = document.getElementById('fp-anchor-query');
    var anchorSuggestions = document.getElementById('fp-anchor-suggestions');
    var surprise = document.getElementById('fp-surprise');
    var surpriseName = document.getElementById('fp-surprise-name');
    var surpriseValue = document.getElementById('fp-surprise-value');
    var analyzeDefault = analyzeButton.querySelector('span').textContent;
    var mixDefault = mixButton.querySelector('span').textContent;
    var kindLabels = optionLabels(document.getElementById('fp-positive-kind'));
    var hardKinds = ['genre', 'theme', 'mood', 'pace'];
    var state = emptyState();
    var analyzedQuery = '';
    var analyzeController = null;
    var mixController = null;
    var suggestController = null;
    var suggestTimer = null;
    var activeSuggestion = -1;
    var ritualTimers = [];
    var ritualRun = 0;
    var minimumRitualDuration = 2200;
    var selectionId = '';
    var motionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

    function emptyState() {
      return {
        normalizedQuery: '',
        residualQuery: '',
        positive: [],
        negative: [],
        anchors: [],
        filters: { in_stock: true },
        surprise: 0.35
      };
    }

    function optionLabels(select) {
      var labels = {};
      Array.prototype.forEach.call(select.options, function (option) {
        labels[option.value] = option.textContent;
      });
      return labels;
    }

    function text(name) {
      return root.getAttribute('data-' + name) || '';
    }

    function setBusy(button, busy, busyLabel, defaultLabel) {
      button.disabled = busy;
      button.setAttribute('aria-busy', busy ? 'true' : 'false');
      button.querySelector('span').textContent = busy ? busyLabel : defaultLabel;
    }

    function setStatus(message, type) {
      status.textContent = message || '';
      status.className = 'fp-alchemy-status' + (type ? ' fp-alchemy-status--' + type : '');
    }

    function updateCounter() {
      counter.textContent = query.value.length + ' / 500';
    }

    function requestJson(url, options) {
      return fetch(url, options).then(function (response) {
        return response.json().catch(function () {
          throw new Error(text('generic-error'));
        }).then(function (payload) {
          if (!response.ok || !payload || payload.success === false) {
            var message = payload && payload.error && payload.error.message
              ? payload.error.message
              : text('generic-error');
            throw new Error(message);
          }
          return payload;
        });
      });
    }

    function postJson(url, payload, signal) {
      return requestJson(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
        signal: signal
      });
    }

    function analyticsRecipe() {
      var payload = buildPayload();
      delete payload.query;
      delete payload.limit;
      return payload;
    }

    function newSelectionId() {
      var bytes = new Uint8Array(16);
      if (window.crypto && window.crypto.getRandomValues) {
        window.crypto.getRandomValues(bytes);
      } else {
        for (var index = 0; index < bytes.length; index++) {
          bytes[index] = Math.floor(Math.random() * 256);
        }
      }
      return Array.prototype.map.call(bytes, function (value) {
        return ('0' + value.toString(16)).slice(-2);
      }).join('');
    }

    function signal(eventType, details) {
      var url = root.getAttribute('data-event-url');
      if (!url) { return Promise.resolve(false); }
      details = details || {};
      var payload = {
        _token: root.getAttribute('data-alchemy-token'),
        event_type: eventType,
        selection_id: selectionId,
        recipe: analyticsRecipe(),
        product_id: details.product_id || 0,
        position: details.position || 0,
        metadata: details.metadata || {}
      };
      return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'same-origin',
        keepalive: true,
        body: JSON.stringify(payload)
      }).then(function (response) {
        return response.ok;
      }).catch(function () {
        // Analytics is deliberately best-effort and never blocks the recipe editor.
        return false;
      });
    }

    function analyze() {
      var value = query.value.trim();
      if (!hasMeaningfulText(value)) {
        query.focus();
        setStatus(text('query-required'), 'error');
        return;
      }
      if (analyzeController) {
        analyzeController.abort();
      }
      analyzeController = window.AbortController ? new AbortController() : null;
      setBusy(analyzeButton, true, text('analyzing-label'), analyzeDefault);
      mixButton.disabled = true;
      setStatus(text('analyzing-label'), 'working');

      postJson(root.getAttribute('data-analyze-url'), {
        query: value,
        locale: document.documentElement.lang === 'en-gb' ? 'en-GB' : 'ru-RU'
      }, analyzeController ? analyzeController.signal : undefined).then(function (payload) {
        applyAnalysis(payload.analysis, value);
        signal('analysis_complete');
        setStatus(text('analysis-ready'), 'success');
      }).catch(function (error) {
        if (error.name !== 'AbortError') {
          setStatus(error.message || text('generic-error'), 'error');
        }
      }).then(function () {
        setBusy(analyzeButton, false, text('analyzing-label'), analyzeDefault);
        updateMixAvailability();
      });
    }

    function applyAnalysis(analysis, originalQuery) {
      state = emptyState();
      state.normalizedQuery = analysis.normalized_query || originalQuery;
      state.residualQuery = typeof analysis.residual_query === 'string'
        ? analysis.residual_query
        : (analysis.unresolved_fragments || []).join(' ');
      state.positive = normalizeIngredients(analysis.positive, false);
      state.negative = normalizeIngredients(analysis.negative, true);
      state.anchors = normalizeAnchors(analysis.anchors);
      state.filters = normalizeFilters(analysis.filters || {});
      analyzedQuery = query.value.trim();
      resetResults();
      recipe.hidden = false;
      recipeEmpty.hidden = true;
      applyFilterFields();
      renderIngredients();
      renderAnchors();
      renderNotices(analysisNotices, analysis.warnings || [], analysis.unresolved_fragments || []);
      updateSurprise();
    }

    function normalizeIngredients(items, negative) {
      if (!Array.isArray(items)) {
        return [];
      }
      return items.slice(0, 20).map(function (item) {
        var value = {
          kind: kindLabels[item.kind] ? item.kind : 'freeform',
          value: String(item.value || '').trim().slice(0, 120),
          weight: clampNumber(item.weight, 0.1, 1, 1)
        };
        if (negative) {
          value.mode = hardKinds.indexOf(value.kind) !== -1 && item.mode === 'exclude' ? 'exclude' : 'avoid';
        }
        return value;
      }).filter(function (item) { return item.value !== ''; });
    }

    function normalizeAnchors(items) {
      if (!Array.isArray(items)) {
        return [];
      }
      return items.slice(0, 3).map(function (item) {
        return {
          product_id: parseInt(item.product_id, 10),
          title: String(item.title || ''),
          author: String(item.author || ''),
          thumb: String(item.thumb || ''),
          href: String(item.href || '#'),
          weight: clampNumber(item.weight, 0.1, 1, 1),
          aspects: Array.isArray(item.aspects) ? item.aspects.slice(0, 5) : []
        };
      }).filter(function (item) { return item.product_id > 0; });
    }

    function normalizeFilters(filters) {
      var output = { in_stock: filters.in_stock !== false };
      ['price_min', 'price_max', 'pages_min', 'pages_max', 'year_min', 'year_max'].forEach(function (name) {
        if (filters[name] !== null && filters[name] !== undefined && filters[name] !== '') {
          output[name] = Number(filters[name]);
        }
      });
      output.age_ratings = Array.isArray(filters.age_ratings) ? filters.age_ratings.slice(0, 1) : [];
      return output;
    }

    function clampNumber(value, min, max, fallback) {
      value = Number(value);
      return isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback;
    }

    function renderIngredients() {
      renderIngredientList(positiveList, state.positive, false);
      renderIngredientList(negativeList, state.negative, true);
      document.getElementById('fp-positive-count').textContent = state.positive.length;
      document.getElementById('fp-negative-count').textContent = state.negative.length;
      updateMixAvailability();
    }

    function renderIngredientList(container, items, negative) {
      container.replaceChildren();
      items.forEach(function (item, index) {
        var row = document.createElement('article');
        row.className = 'fp-alchemy-ingredient' + (negative ? ' fp-alchemy-ingredient--negative' : '');

        var main = document.createElement('div');
        main.className = 'fp-alchemy-ingredient__main';
        var kind = document.createElement('select');
        kind.setAttribute('aria-label', document.getElementById(negative ? 'fp-negative-kind' : 'fp-positive-kind').getAttribute('aria-label'));
        Object.keys(kindLabels).forEach(function (key) {
          var option = document.createElement('option');
          option.value = key;
          option.textContent = kindLabels[key];
          option.selected = item.kind === key;
          kind.appendChild(option);
        });
        var value = document.createElement('input');
        value.type = 'text';
        value.maxLength = 120;
        value.value = item.value;
        value.setAttribute('aria-label', kindLabels[item.kind] + ': ' + item.value);
        main.appendChild(kind);
        main.appendChild(value);

        var controls = document.createElement('div');
        controls.className = 'fp-alchemy-ingredient__controls';
        var weightWrap = document.createElement('label');
        weightWrap.className = 'fp-alchemy-weight';
        var weightLabel = document.createElement('span');
        weightLabel.className = 'sr-only';
        weightLabel.textContent = text('weight-label');
        var weight = document.createElement('input');
        weight.type = 'range';
        weight.min = '0.1';
        weight.max = '1';
        weight.step = '0.1';
        weight.value = item.weight;
        var initialWeight = item.weight;
        var weightOutput = document.createElement('output');
        weightOutput.textContent = Math.round(item.weight * 100) + '%';
        weightWrap.appendChild(weightLabel);
        weightWrap.appendChild(weight);
        weightWrap.appendChild(weightOutput);
        var strictMode = negative && item.mode === 'exclude' && hardKinds.indexOf(item.kind) !== -1;
        if (strictMode) {
          controls.classList.add('fp-alchemy-ingredient__controls--strict');
        } else {
          controls.appendChild(weightWrap);
        }

        var mode = null;
        if (negative) {
          mode = document.createElement('select');
          mode.className = 'fp-alchemy-mode';
          mode.setAttribute('aria-label', text('mode-label'));
          var avoid = document.createElement('option');
          avoid.value = 'avoid';
          avoid.textContent = text('avoid-label');
          mode.appendChild(avoid);
          if (hardKinds.indexOf(item.kind) !== -1) {
            var exclude = document.createElement('option');
            exclude.value = 'exclude';
            exclude.textContent = text('exclude-label');
            mode.appendChild(exclude);
          }
          mode.value = item.mode;
          controls.appendChild(mode);
        }

        var remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'fp-alchemy-remove';
        remove.setAttribute('aria-label', text('remove-label') + ': ' + item.value);
        remove.title = text('remove-label');
        var removeIcon = document.createElement('i');
        removeIcon.className = 'fa fa-times';
        removeIcon.setAttribute('aria-hidden', 'true');
        remove.appendChild(removeIcon);
        controls.appendChild(remove);

        kind.addEventListener('change', function () {
          item.kind = kind.value;
          if (negative && hardKinds.indexOf(item.kind) === -1) {
            item.mode = 'avoid';
          }
          renderIngredients();
        });
        value.addEventListener('change', function () {
          item.value = value.value.trim().slice(0, 120);
          if (!item.value) {
            items.splice(index, 1);
            renderIngredients();
            signal('ingredient_remove', { metadata: {
              ingredient_kind: item.kind,
              ingredient_side: negative ? 'negative' : 'positive'
            } });
            return;
          }
          renderIngredients();
        });
        weight.addEventListener('input', function () {
          item.weight = Number(weight.value);
          weightOutput.textContent = Math.round(item.weight * 100) + '%';
        });
        weight.addEventListener('change', function () {
          signal('weight_change', { metadata: {
            source: 'ingredient',
            ingredient_kind: item.kind,
            ingredient_side: negative ? 'negative' : 'positive',
            previous_weight: initialWeight,
            weight: item.weight
          } });
          initialWeight = item.weight;
        });
        if (mode) {
          mode.addEventListener('change', function () {
            item.mode = mode.value;
            renderIngredients();
          });
        }
        remove.addEventListener('click', function () {
          items.splice(index, 1);
          renderIngredients();
          signal('ingredient_remove', { metadata: {
            ingredient_kind: item.kind,
            ingredient_side: negative ? 'negative' : 'positive'
          } });
        });

        row.appendChild(main);
        row.appendChild(controls);
        container.appendChild(row);
      });
    }

    function addIngredient(negative) {
      var prefix = negative ? 'fp-negative-' : 'fp-positive-';
      var kind = document.getElementById(prefix + 'kind').value;
      var input = document.getElementById(prefix + 'value');
      var value = input.value.trim().slice(0, 120);
      if (!value) {
        setStatus(text('ingredient-required'), 'error');
        input.focus();
        return;
      }
      var key = kind + ':' + value.toLocaleLowerCase();
      var all = state.positive.concat(state.negative);
      var duplicate = all.some(function (item) {
        return item.kind + ':' + item.value.toLocaleLowerCase() === key;
      });
      if (duplicate) {
        setStatus(text('duplicate'), 'error');
        input.focus();
        return;
      }
      var ingredient = { kind: kind, value: value, weight: 1 };
      if (negative) {
        ingredient.mode = 'avoid';
        state.negative.push(ingredient);
      } else {
        state.positive.push(ingredient);
      }
      input.value = '';
      setStatus('', '');
      renderIngredients();
      signal('ingredient_add', { metadata: {
        ingredient_kind: ingredient.kind,
        ingredient_side: negative ? 'negative' : 'positive'
      } });
      input.focus();
    }

    function updateAnchorRangeFill(input) {
      var minimum = Number(input.min);
      var maximum = Number(input.max);
      var progress = maximum > minimum
        ? ((Number(input.value) - minimum) / (maximum - minimum)) * 100
        : 0;
      input.style.setProperty('--fp-range-progress', Math.max(0, Math.min(100, progress)) + '%');
    }

    function renderAnchors() {
      anchorList.replaceChildren();
      state.anchors.forEach(function (anchor, index) {
        var card = document.createElement('article');
        card.className = 'fp-alchemy-anchor';
        var link = document.createElement('a');
        link.href = anchor.href || '#';
        link.className = 'fp-alchemy-anchor__cover';
        var image = document.createElement('img');
        image.src = anchor.thumb;
        image.alt = anchor.title;
        image.loading = 'lazy';
        link.appendChild(image);

        var body = document.createElement('div');
        body.className = 'fp-alchemy-anchor__body';
        var author = document.createElement('span');
        author.textContent = anchor.author;
        var title = document.createElement('h4');
        var titleLink = document.createElement('a');
        titleLink.href = anchor.href || '#';
        titleLink.textContent = anchor.title;
        title.appendChild(titleLink);
        var aspects = document.createElement('input');
        aspects.type = 'text';
        aspects.maxLength = 300;
        aspects.value = anchor.aspects.join(', ');
        aspects.placeholder = text('anchor-aspects-placeholder');
        aspects.setAttribute('aria-label', text('anchor-aspects-label') + ': ' + anchor.title);

        var controls = document.createElement('div');
        controls.className = 'fp-alchemy-anchor__controls';
        var weight = document.createElement('input');
        weight.type = 'range';
        weight.min = '0.1';
        weight.max = '1';
        weight.step = '0.1';
        weight.value = anchor.weight;
        updateAnchorRangeFill(weight);
        var initialWeight = anchor.weight;
        weight.setAttribute('aria-label', text('weight-label') + ': ' + anchor.title);
        var output = document.createElement('output');
        output.textContent = Math.round(anchor.weight * 100) + '%';
        var remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'fp-alchemy-remove';
        remove.setAttribute('aria-label', text('remove-label') + ': ' + anchor.title);
        var icon = document.createElement('i');
        icon.className = 'fa fa-times';
        icon.setAttribute('aria-hidden', 'true');
        remove.appendChild(icon);

        aspects.addEventListener('change', function () {
          var used = {};
          anchor.aspects = aspects.value.split(',').map(function (value) {
            return value.trim().slice(0, 120);
          }).filter(function (value) {
            var key = value.toLocaleLowerCase();
            if (!value || used[key]) { return false; }
            used[key] = true;
            return true;
          }).slice(0, 5);
          aspects.value = anchor.aspects.join(', ');
        });
        weight.addEventListener('input', function () {
          anchor.weight = Number(weight.value);
          output.textContent = Math.round(anchor.weight * 100) + '%';
          updateAnchorRangeFill(weight);
        });
        weight.addEventListener('change', function () {
          signal('weight_change', { product_id: anchor.product_id, metadata: {
            source: 'anchor',
            previous_weight: initialWeight,
            weight: anchor.weight
          } });
          initialWeight = anchor.weight;
        });
        remove.addEventListener('click', function () {
          state.anchors.splice(index, 1);
          renderAnchors();
          signal('anchor_remove', { product_id: anchor.product_id });
        });

        body.appendChild(author);
        body.appendChild(title);
        body.appendChild(aspects);
        controls.appendChild(weight);
        controls.appendChild(output);
        controls.appendChild(remove);
        body.appendChild(controls);
        card.appendChild(link);
        card.appendChild(body);
        anchorList.appendChild(card);
      });
      document.getElementById('fp-anchor-count').textContent = state.anchors.length + ' / 3';
      anchorQuery.disabled = state.anchors.length >= 3;
      anchorQuery.placeholder = state.anchors.length >= 3 ? text('anchor-limit') : anchorQuery.getAttribute('data-default-placeholder') || anchorQuery.placeholder;
      closeSuggestions();
      updateMixAvailability();
    }

    function searchAnchors() {
      clearTimeout(suggestTimer);
      var value = anchorQuery.value.trim();
      if (value.length < 2 || state.anchors.length >= 3) {
        closeSuggestions();
        return;
      }
      suggestTimer = setTimeout(function () {
        if (suggestController) {
          suggestController.abort();
        }
        suggestController = window.AbortController ? new AbortController() : null;
        var url = root.getAttribute('data-suggest-url') + (root.getAttribute('data-suggest-url').indexOf('?') === -1 ? '?' : '&') + 'q=' + encodeURIComponent(value);
        requestJson(url, {
          headers: { 'Accept': 'application/json' },
          credentials: 'same-origin',
          signal: suggestController ? suggestController.signal : undefined
        }).then(function (payload) {
          renderSuggestions(payload.suggestions || []);
        }).catch(function (error) {
          if (error.name !== 'AbortError') {
            renderSuggestions([], error.message || text('generic-error'));
          }
        });
      }, 180);
    }

    function renderSuggestions(items, message) {
      anchorSuggestions.replaceChildren();
      activeSuggestion = -1;
      var available = items.filter(function (item) {
        return !state.anchors.some(function (anchor) { return anchor.product_id === Number(item.product_id); });
      });
      if (!available.length) {
        var empty = document.createElement('p');
        empty.className = 'fp-alchemy-suggestions__empty';
        empty.textContent = message || text('anchor-empty');
        anchorSuggestions.appendChild(empty);
      } else {
        available.forEach(function (item, index) {
          var button = document.createElement('button');
          button.type = 'button';
          button.className = 'fp-alchemy-suggestion';
          button.setAttribute('role', 'option');
          button.setAttribute('aria-selected', 'false');
          button.dataset.index = index;
          var image = document.createElement('img');
          image.src = item.thumb;
          image.alt = '';
          var copy = document.createElement('span');
          var strong = document.createElement('strong');
          strong.textContent = item.title;
          var small = document.createElement('small');
          small.textContent = item.author || '';
          copy.appendChild(strong);
          copy.appendChild(small);
          button.appendChild(image);
          button.appendChild(copy);
          button.addEventListener('click', function () { addAnchor(item); });
          anchorSuggestions.appendChild(button);
        });
      }
      anchorSuggestions.hidden = false;
      anchorQuery.setAttribute('aria-expanded', 'true');
    }

    function addAnchor(item) {
      if (state.anchors.length >= 3) {
        setStatus(text('anchor-limit'), 'error');
        return;
      }
      state.anchors.push({
        product_id: Number(item.product_id),
        title: String(item.title || ''),
        author: String(item.author || ''),
        thumb: String(item.thumb || ''),
        href: String(item.href || '#'),
        weight: 1,
        aspects: []
      });
      anchorQuery.value = '';
      renderAnchors();
      signal('anchor_add', { product_id: Number(item.product_id) });
    }

    function closeSuggestions() {
      anchorSuggestions.hidden = true;
      anchorSuggestions.replaceChildren();
      anchorQuery.setAttribute('aria-expanded', 'false');
      anchorQuery.removeAttribute('aria-activedescendant');
      activeSuggestion = -1;
    }

    function moveSuggestion(direction) {
      var options = anchorSuggestions.querySelectorAll('.fp-alchemy-suggestion');
      if (!options.length) { return; }
      activeSuggestion = (activeSuggestion + direction + options.length) % options.length;
      Array.prototype.forEach.call(options, function (option, index) {
        var selected = index === activeSuggestion;
        option.setAttribute('aria-selected', selected ? 'true' : 'false');
        option.id = 'fp-anchor-option-' + index;
      });
      anchorQuery.setAttribute('aria-activedescendant', options[activeSuggestion].id);
    }

    function applyFilterFields() {
      ['price_min', 'price_max', 'pages_min', 'pages_max', 'year_min', 'year_max'].forEach(function (name) {
        document.getElementById('fp-' + name.replace('_', '-')).value = state.filters[name] !== undefined ? state.filters[name] : '';
      });
      document.getElementById('fp-age').value = state.filters.age_ratings && state.filters.age_ratings[0] ? state.filters.age_ratings[0] : '';
      document.getElementById('fp-in-stock').checked = state.filters.in_stock !== false;
    }

    function readFilters() {
      var output = { in_stock: document.getElementById('fp-in-stock').checked };
      [['price_min', false], ['price_max', false], ['pages_min', true], ['pages_max', true], ['year_min', true], ['year_max', true]].forEach(function (definition) {
        var element = document.getElementById('fp-' + definition[0].replace('_', '-'));
        if (element.value !== '') {
          var value = Number(element.value);
          if (isFinite(value) && value >= 0) {
            output[definition[0]] = definition[1] ? Math.round(value) : value;
          }
        }
      });
      [['price_min', 'price_max'], ['pages_min', 'pages_max'], ['year_min', 'year_max']].forEach(function (pair) {
        if (output[pair[0]] !== undefined && output[pair[1]] !== undefined && output[pair[0]] > output[pair[1]]) {
          var held = output[pair[0]];
          output[pair[0]] = output[pair[1]];
          output[pair[1]] = held;
          document.getElementById('fp-' + pair[0].replace('_', '-')).value = output[pair[0]];
          document.getElementById('fp-' + pair[1].replace('_', '-')).value = output[pair[1]];
        }
      });
      var age = document.getElementById('fp-age').value;
      output.age_ratings = age ? [age] : [];
      output.authors = [];
      output.genres = [];
      output.moods = [];
      output.paces = [];
      return output;
    }

    function updateSurprise() {
      state.surprise = Number(surprise.value);
      surpriseValue.textContent = Math.round(state.surprise * 100) + '%';
      if (state.surprise <= 0.2) {
        surpriseName.textContent = root.getAttribute('data-surprise-precise') || 'Точное попадание';
      } else if (state.surprise <= 0.5) {
        surpriseName.textContent = root.getAttribute('data-surprise-balanced') || 'Равновесие';
      } else if (state.surprise <= 0.75) {
        surpriseName.textContent = root.getAttribute('data-surprise-brave') || 'Смелый выбор';
      } else {
        surpriseName.textContent = root.getAttribute('data-surprise-wild') || 'Неожиданный опыт';
      }
    }

    function updateMixAvailability() {
      var hasRecipe = !recipe.hidden && (query.value.trim() || state.anchors.length || state.positive.length);
      var dirty = analyzedQuery && query.value.trim() !== analyzedQuery;
      mixButton.disabled = !hasRecipe || dirty || analyzeButton.getAttribute('aria-busy') === 'true';
    }

    function buildPayload() {
      return {
        query: state.normalizedQuery || query.value.trim(),
        residual_query: state.residualQuery,
        anchors: state.anchors.map(function (anchor) {
          return {
            product_id: anchor.product_id,
            weight: clampNumber(anchor.weight, 0.1, 1, 1),
            aspects: anchor.aspects.slice(0, 5)
          };
        }),
        positive: cleanIngredientPayload(state.positive, false),
        negative: cleanIngredientPayload(state.negative, true),
        filters: readFilters(),
        surprise: Number(surprise.value),
        limit: 12
      };
    }

    function cleanIngredientPayload(items, negative) {
      return items.map(function (item) {
        var output = {
          kind: item.kind,
          value: item.value.trim().slice(0, 120),
          weight: clampNumber(item.weight, 0.1, 1, 1)
        };
        if (negative) {
          output.mode = hardKinds.indexOf(item.kind) !== -1 && item.mode === 'exclude' ? 'exclude' : 'avoid';
        }
        return output;
      }).filter(function (item) { return item.value !== ''; });
    }

    function validatePayload(payload) {
      var used = {};
      var valid = true;
      payload.positive.concat(payload.negative).forEach(function (item) {
        var key = item.kind + ':' + item.value.toLocaleLowerCase();
        if (used[key]) { valid = false; }
        used[key] = true;
      });
      if (!valid) {
        setStatus(text('duplicate'), 'error');
      }
      if (!payload.anchors.length && !payload.positive.length && !hasMeaningfulText(payload.query)) {
        setStatus(text('query-required'), 'error');
        return false;
      }
      return valid;
    }

    function hasMeaningfulText(value) {
      return /[A-Za-zА-Яа-яЁё0-9]/.test(value || '');
    }

    function reducedMotion() {
      return motionQuery && motionQuery.matches;
    }

    function clearRitualTimers() {
      ritualTimers.forEach(function (timer) { window.clearTimeout(timer); });
      ritualTimers = [];
    }

    function ritualIngredients(payload) {
      var tokens = [];
      (payload.anchors || []).forEach(function (item) {
        var fullAnchor = state.anchors.filter(function (anchor) { return anchor.product_id === item.product_id; })[0];
        tokens.push({ label: fullAnchor ? fullAnchor.title : '', weight: item.weight, type: 'anchor' });
      });
      (payload.positive || []).forEach(function (item) {
        tokens.push({ label: item.value, weight: item.weight, type: 'positive' });
      });
      (payload.negative || []).forEach(function (item) {
        tokens.push({ label: item.value, weight: item.weight, type: 'negative' });
      });
      return tokens.slice(0, 9);
    }

    function setRitualPhase(index) {
      Array.prototype.forEach.call(ritual.querySelectorAll('[data-ritual-phase]'), function (phase, phaseIndex) {
        phase.classList.toggle('is-active', phaseIndex === index);
        phase.classList.toggle('is-passed', phaseIndex < index);
      });
    }

    function animateRitualToken(token, index, total) {
      if (reducedMotion() || !token.animate) { return; }
      var angle = ((Math.PI * 2) / Math.max(total, 1)) * index - (Math.PI / 2);
      var radiusX = 132 + (index % 3) * 18;
      var radiusY = 82 + (index % 2) * 22;
      var x = Math.cos(angle) * radiusX;
      var y = Math.sin(angle) * radiusY;
      token.animate([
        { opacity: 0, transform: 'translate(calc(-50% + ' + x + 'px), calc(-50% + ' + y + 'px)) scale(.72)' },
        { opacity: 1, offset: .18 },
        { opacity: 1, transform: 'translate(-50%, -50%) scale(1)', offset: .82 },
        { opacity: 0, transform: 'translate(-50%, -50%) scale(.3)' }
      ], {
        duration: 720,
        delay: index * 55,
        easing: 'cubic-bezier(.24,.8,.25,1)',
        fill: 'both'
      });
    }

    function startRitual(payload) {
      ritualRun += 1;
      clearRitualTimers();
      output.classList.add('has-mixed');
      ritual.hidden = false;
      ritual.className = 'fp-alchemy-ritual is-running';
      ritualTitle.textContent = text('ritual-title') || ritualTitle.textContent;
      ritualTokens.replaceChildren();
      results.replaceChildren();
      resultMeta.hidden = true;
      resultsEmpty.hidden = true;

      var ingredients = ritualIngredients(payload);
      ingredients.forEach(function (ingredient, index) {
        var token = document.createElement('span');
        token.className = 'fp-alchemy-ritual__token fp-alchemy-ritual__token--' + ingredient.type;
        token.textContent = ingredient.label;
        token.style.fontSize = (7.5 + clampNumber(ingredient.weight, 0.1, 1, 1) * 2.5) + 'px';
        ritualTokens.appendChild(token);
        animateRitualToken(token, index, ingredients.length);
      });

      setRitualPhase(0);
      if (!reducedMotion()) {
        ritualTimers.push(window.setTimeout(function () { setRitualPhase(1); }, 700));
        ritualTimers.push(window.setTimeout(function () { setRitualPhase(2); }, 1450));
      } else {
        setRitualPhase(2);
      }

      if (resultsStage && resultsStage.scrollIntoView) {
        resultsStage.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
      }
      return { run: ritualRun, startedAt: Date.now() };
    }

    function waitForRitualMinimum(session) {
      if (reducedMotion()) { return Promise.resolve(); }
      var elapsed = Date.now() - session.startedAt;
      var remaining = Math.max(0, minimumRitualDuration - elapsed);
      return new Promise(function (resolve) {
        window.setTimeout(resolve, remaining);
      });
    }

    function finishRitual(outcome, run) {
      if (run !== ritualRun) { return; }
      clearRitualTimers();
      setRitualPhase(3);
      ritual.classList.remove('is-running');
      ritual.classList.add(outcome === 'success' ? 'is-complete' : 'is-error');
      if (outcome === 'success') {
        ritualTitle.textContent = text('ritual-complete');
      }
      if (reducedMotion()) {
        ritual.hidden = true;
        return;
      }
      ritualTimers.push(window.setTimeout(function () {
        if (run !== ritualRun) { return; }
        ritual.classList.add('is-leaving');
      }, 120));
      ritualTimers.push(window.setTimeout(function () {
        if (run !== ritualRun) { return; }
        ritual.hidden = true;
        ritual.className = 'fp-alchemy-ritual';
      }, 560));
    }

    function revealResultCards() {
      var cards = results.querySelectorAll('.fp-alchemy-book');
      Array.prototype.forEach.call(cards, function (card, index) {
        if (reducedMotion() || !card.animate) {
          card.style.opacity = '';
          return;
        }
        var delay = index < 3 ? index * 75 : 210;
        var animation = card.animate([
          { opacity: 0, transform: 'translateY(18px) scale(.985)' },
          { opacity: 1, transform: 'translateY(0) scale(1)' }
        ], {
          duration: 420,
          delay: delay,
          easing: 'cubic-bezier(.2,.75,.25,1)',
          fill: 'both'
        });
        animation.onfinish = function () {
          animation.cancel();
          card.style.opacity = '';
        };
      });
    }

    function mixRecipe() {
      var payload = buildPayload();
      if (!validatePayload(payload)) {
        return;
      }
      if (mixController) {
        mixController.abort();
      }
      mixController = window.AbortController ? new AbortController() : null;
      setBusy(mixButton, true, text('mixing-label'), mixDefault);
      setStatus(text('mixing-label'), 'working');
      results.setAttribute('aria-busy', 'true');
      resultNotices.replaceChildren();
      selectionId = newSelectionId();
      var activeRitual = startRitual(payload);

      postJson(root.getAttribute('data-recommend-url'), payload, mixController ? mixController.signal : undefined).then(function (response) {
        return waitForRitualMinimum(activeRitual).then(function () {
          if (activeRitual.run !== ritualRun) { return; }
          renderResults(response);
          signal('recommendation_shown', { metadata: {
            result_count: response.results ? response.results.length : 0,
            result_product_ids: (response.results || []).map(function (product) { return product.product_id; })
          } });
          revealResultCards();
          finishRitual('success', activeRitual.run);
          setStatus(
            response.results && response.results.length ? text('mix-ready') : text('no-results'),
            response.results && response.results.length ? 'success' : ''
          );
        });
      }).catch(function (error) {
        if (error.name !== 'AbortError') {
          finishRitual('error', activeRitual.run);
          setStatus(error.message || text('generic-error'), 'error');
          renderErrorNotice(error.message || text('generic-error'));
        }
      }).then(function () {
        results.removeAttribute('aria-busy');
        setBusy(mixButton, false, text('mixing-label'), mixDefault);
        updateMixAvailability();
      });
    }

    function renderNotices(container, warnings, unresolved) {
      container.replaceChildren();
      warnings.forEach(function (warning) {
        appendNotice(container, warningMessage(warning), 'warning');
      });
      if (unresolved.length) {
        appendNotice(container, 'Часть формулировки оставлена в общем смысле: ' + unresolved.join('; '), 'info');
      }
    }

    function warningMessage(warning) {
      var messages = {
        limited_locale: 'Структурный разбор английского текста пока ограничен, но весь запрос участвует в смысловом поиске.',
        unverified_content_avoidance: 'Отсутствие чувствительного содержания нельзя гарантировать по текущим данным каталога: применено мягкое избегание.',
        anchors_truncated: 'Распознаны только первые три книги-ориентира.',
        hard_exclusion_downgraded: 'Одно из строгих исключений заменено мягким избеганием: данных каталога недостаточно для гарантии.',
        no_candidates: 'Строгие ограничения отсекли все книги.'
      };
      return messages[warning.code] || warning.message || warning.code;
    }

    function appendNotice(container, message, type) {
      if (!message) { return; }
      var notice = document.createElement('div');
      notice.className = 'fp-alchemy-notice fp-alchemy-notice--' + type;
      var icon = document.createElement('i');
      icon.className = type === 'warning' ? 'fa fa-exclamation-circle' : 'fa fa-info-circle';
      icon.setAttribute('aria-hidden', 'true');
      var copy = document.createElement('span');
      copy.textContent = message;
      notice.appendChild(icon);
      notice.appendChild(copy);
      container.appendChild(notice);
    }

    function renderResults(payload) {
      results.replaceChildren();
      resultsEmpty.hidden = true;
      resultMeta.hidden = false;
      resultMeta.textContent = (payload.count || 0) + ' ' + text('results-count');
      renderNotices(resultNotices, payload.warnings || [], []);

      if (payload.state === 'partial' && payload.results && payload.results.length) {
        appendNotice(resultNotices, text('partial-results'), 'info');
      }

      if (!payload.results || !payload.results.length) {
        resultsEmpty.hidden = false;
        resultsEmpty.querySelector('p').textContent = payload.state === 'no_candidates'
          ? text('no-results-filters')
          : text('no-results');
        renderRelaxations(payload.relaxations || []);
        return;
      }
      payload.results.forEach(function (product, index) {
        results.appendChild(createProductCard(product, index + 1));
      });
      renderRelaxations(payload.relaxations || []);
    }

    function resetResults() {
      results.replaceChildren();
      resultNotices.replaceChildren();
      resultMeta.hidden = true;
      resultsEmpty.hidden = false;
      resultsEmpty.querySelector('p').textContent = text('results-empty');
    }

    function renderRelaxations(relaxations) {
      if (!relaxations.length) { return; }
      var box = document.createElement('div');
      box.className = 'fp-alchemy-relaxations';
      var title = document.createElement('strong');
      title.textContent = text('relaxations-label');
      var list = document.createElement('ul');
      relaxations.forEach(function (value) {
        var item = document.createElement('li');
        item.textContent = value;
        list.appendChild(item);
      });
      box.appendChild(title);
      box.appendChild(list);
      resultNotices.appendChild(box);
    }

    function createProductCard(product, position) {
      var card = document.createElement('article');
      card.className = 'fp-alchemy-book fp-alchemy-book--' + product.band;
      var cover = document.createElement('a');
      cover.href = product.href;
      cover.className = 'fp-alchemy-book__cover';
      cover.addEventListener('click', function () {
        signal('product_open', { product_id: product.product_id, position: position, metadata: { band: product.band } });
      });
      var image = document.createElement('img');
      image.src = product.thumb;
      image.alt = product.name;
      image.loading = 'lazy';
      cover.appendChild(image);

      var band = document.createElement('span');
      band.className = 'fp-alchemy-band';
      band.textContent = text('band-' + product.band) || text('band-balanced');
      cover.appendChild(band);

      var body = document.createElement('div');
      body.className = 'fp-alchemy-book__body';
      var meta = document.createElement('div');
      meta.className = 'fp-alchemy-book__meta';
      var author = document.createElement('span');
      author.className = 'fp-alchemy-book__author';
      author.textContent = product.author || '\u00a0';
      meta.appendChild(author);
      var ratingValue = Number(product.external_rating || (product.local_rating_count ? product.local_rating : 0));
      if (ratingValue > 0) {
        var rating = document.createElement('span');
        rating.className = 'fp-alchemy-book__rating';
        rating.innerHTML = '<i class="fa fa-star" aria-hidden="true"></i><span></span>';
        rating.querySelector('span').textContent = ratingValue.toFixed(1).replace('.', text('decimal-point'));
        rating.setAttribute('aria-label', rating.querySelector('span').textContent + ' из 5');
        meta.appendChild(rating);
      }
      var heading = document.createElement('h3');
      var headingLink = document.createElement('a');
      headingLink.href = product.href;
      headingLink.textContent = product.name;
      headingLink.addEventListener('click', function () {
        signal('product_open', { product_id: product.product_id, position: position, metadata: { band: product.band } });
      });
      heading.appendChild(headingLink);

      var evidence = document.createElement('div');
      evidence.className = 'fp-alchemy-book__evidence';
      var evidenceTitle = document.createElement('strong');
      evidenceTitle.textContent = text('matched-label');
      evidence.appendChild(evidenceTitle);
      var evidenceValues = document.createElement('div');
      evidenceValues.className = 'fp-alchemy-book__matches';
      matchingCharacteristics(product).forEach(function (value) {
        var characteristic = document.createElement('span');
        characteristic.innerHTML = '<i class="fa fa-check" aria-hidden="true"></i><span></span>';
        characteristic.querySelector('span').textContent = value;
        evidenceValues.appendChild(characteristic);
      });
      evidence.appendChild(evidenceValues);

      var footer = document.createElement('div');
      footer.className = 'fp-alchemy-book__footer';
      var price = document.createElement('div');
      price.className = 'fp-alchemy-book__price';
      if (product.special) {
        var special = document.createElement('strong');
        special.textContent = product.special;
        var old = document.createElement('s');
        old.textContent = product.price || '';
        price.appendChild(special);
        price.appendChild(old);
      } else {
        price.textContent = product.price || '';
      }
      var actions = document.createElement('div');
      actions.className = 'fp-alchemy-book__actions';
      var cartButton = document.createElement('button');
      cartButton.type = 'button';
      cartButton.className = 'fp-alchemy-cart';
      cartButton.setAttribute('aria-label', text('cart-label') + ': ' + product.name);
      var cartIcon = document.createElement('i');
      cartIcon.className = 'fa fa-shopping-bag';
      cartIcon.setAttribute('aria-hidden', 'true');
      var cartText = document.createElement('span');
      cartText.textContent = text('cart-label');
      cartButton.appendChild(cartIcon);
      cartButton.appendChild(cartText);
      cartButton.addEventListener('click', function () {
        signal('cart', { product_id: product.product_id, position: position, metadata: { band: product.band } });
        if (window.cart && window.cart.add) { window.cart.add(product.product_id, product.minimum || 1); }
      });
      var wishButton = document.createElement('button');
      wishButton.type = 'button';
      wishButton.className = 'fp-alchemy-wish';
      wishButton.title = text('wishlist-label');
      wishButton.setAttribute('aria-label', text('wishlist-label') + ': ' + product.name);
      var wishIcon = document.createElement('i');
      wishIcon.className = 'fa fa-bookmark-o';
      wishIcon.setAttribute('aria-hidden', 'true');
      wishButton.appendChild(wishIcon);
      wishButton.addEventListener('click', function () {
        signal('wishlist', { product_id: product.product_id, position: position, metadata: { band: product.band } });
        if (window.wishlist && window.wishlist.add) { window.wishlist.add(product.product_id); }
      });
      actions.appendChild(cartButton);
      actions.appendChild(wishButton);
      footer.appendChild(price);
      footer.appendChild(actions);

      body.appendChild(meta);
      body.appendChild(heading);
      body.appendChild(evidence);
      body.appendChild(footer);
      card.appendChild(cover);
      card.appendChild(body);
      return card;
    }

    function matchingCharacteristics(product) {
      var values = [];
      function append(value) {
        value = String(value || '').replace(/^\s*(?:совпадает|matched)\s*:\s*/i, '').trim();
        if (!value) { return; }
        var key = value.toLocaleLowerCase();
        var duplicate = values.some(function (existing) {
          var existingKey = existing.toLocaleLowerCase();
          return existingKey === key || existingKey.indexOf(key) !== -1 || key.indexOf(existingKey) !== -1;
        });
        if (!duplicate && values.length < 4) {
          values.push(value);
        }
      }
      (product.matched || []).forEach(append);
      (product.reasons || []).forEach(append);
      return values;
    }

    function renderErrorNotice(message) {
      resultNotices.replaceChildren();
      appendNotice(resultNotices, message, 'warning');
    }

    query.addEventListener('input', function () {
      updateCounter();
      if (analyzedQuery && query.value.trim() !== analyzedQuery) {
        setStatus(text('dirty-label'), 'warning');
      }
      updateMixAvailability();
    });
    analyzeForm.addEventListener('submit', function (event) {
      event.preventDefault();
      analyze();
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-alchemy-example]'), function (button) {
      button.addEventListener('click', function () {
        query.value = button.getAttribute('data-alchemy-example');
        updateCounter();
        analyze();
      });
    });
    document.getElementById('fp-positive-add').addEventListener('submit', function (event) {
      event.preventDefault();
      addIngredient(false);
    });
    document.getElementById('fp-negative-add').addEventListener('submit', function (event) {
      event.preventDefault();
      addIngredient(true);
    });
    surprise.addEventListener('input', updateSurprise);
    mixButton.addEventListener('click', mixRecipe);
    anchorQuery.setAttribute('data-default-placeholder', anchorQuery.placeholder);
    anchorQuery.addEventListener('input', searchAnchors);
    anchorQuery.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault(); moveSuggestion(1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault(); moveSuggestion(-1);
      } else if (event.key === 'Enter' && activeSuggestion >= 0) {
        event.preventDefault();
        var current = anchorSuggestions.querySelectorAll('.fp-alchemy-suggestion')[activeSuggestion];
        if (current) { current.click(); }
      } else if (event.key === 'Escape') {
        closeSuggestions();
      }
    });
    document.addEventListener('click', function (event) {
      if (!event.target.closest('.fp-alchemy-anchor-search')) { closeSuggestions(); }
    });

    updateCounter();
    updateSurprise();
    updateMixAvailability();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAlchemy);
  } else {
    initAlchemy();
  }
}());
