/*
 * New/Edit Organization form: Size Category, Domain, and cascading
 * SubDomain pickers, plus an auto-suggest that fills Size Category from a
 * typed Number of Employees.
 *
 * Same "fetch the whole tree once, filter client-side" approach as
 * geography_picker.js (GET /organizations/classification-tree instead of
 * /geography/tree — these three lookups are tenant-scoped, unlike
 * geography, but the fetch-once/filter-locally shape is identical). The
 * Domain and SubDomain <select> elements start out with just a
 * placeholder option (see organizations/form.html) and are filled in here
 * once the tree arrives; SubDomain is re-filled every time Domain changes.
 *
 * Auto-suggest: whenever the Number of Employees field changes, the Size
 * Category select is set to whichever seeded bucket's [min_employees,
 * max_employees] the typed number falls into (max_employees may be
 * null/blank for the open-ended top bucket). This is a *suggestion*, not a
 * lock — the person can still pick a different Size Category by hand at
 * any time, and once they've done that by hand we stop overwriting their
 * choice on further typing (see `manualSizeCategory` below) unless they
 * clear the field, which un-does the override so auto-suggest resumes.
 *
 * Usage: give the elements ids `number_of_employees`, `size_category_id`,
 * `organization_domain_id`, `organization_subdomain_id` (organizations/
 * form.html does), then call:
 *
 *   initOrganizationClassificationPicker({
 *     initial: { size_category_id, organization_domain_id, organization_subdomain_id }
 *   });
 */
(function () {
  function el(id) { return document.getElementById(id); }

  function fillSelect(select, items, valueKey, labelKey, placeholder) {
    var previous = select.value;
    select.innerHTML = "";
    var opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = placeholder;
    select.appendChild(opt0);
    items.forEach(function (item) {
      var opt = document.createElement("option");
      opt.value = item[valueKey];
      opt.textContent = item[labelKey];
      select.appendChild(opt);
    });
    if (previous) select.value = previous;
  }

  window.initOrganizationClassificationPicker = function (opts) {
    opts = opts || {};
    var initial = opts.initial || {};

    var employeesInput = el("number_of_employees");
    var sizeSelect = el("size_category_id");
    var domainSelect = el("organization_domain_id");
    var subdomainSelect = el("organization_subdomain_id");

    if (!sizeSelect || !domainSelect || !subdomainSelect) {
      return; // form doesn't use the picker
    }

    var tree = null;
    // Starts true whenever an existing organization already has a Size
    // Category saved (edit form) or once the person picks one by hand, so
    // auto-suggest never silently overwrites a deliberate choice.
    var manualSizeCategory = !!initial.size_category_id;

    function subdomainsFor(domainId) {
      if (!tree || !domainId) return [];
      return tree.subdomains.filter(function (s) { return String(s.organization_domain_id) === String(domainId); });
    }

    function refreshSubdomainUI(domainId, selectedSubdomainId) {
      var subs = subdomainsFor(domainId);
      fillSelect(subdomainSelect, subs, "organization_subdomain_id", "label",
        subs.length ? "— Select sub-domain —" : "— None on file for this domain —");
      subdomainSelect.disabled = subs.length === 0;
      if (selectedSubdomainId) subdomainSelect.value = selectedSubdomainId;
    }

    function suggestSizeCategory() {
      if (!tree || manualSizeCategory || !employeesInput) return;
      var n = parseInt(employeesInput.value, 10);
      if (isNaN(n) || n < 0) return;
      var match = tree.size_categories.find(function (c) {
        var min = c.min_employees == null ? 0 : c.min_employees;
        var max = c.max_employees == null ? Infinity : c.max_employees;
        return n >= min && n <= max;
      });
      if (match) sizeSelect.value = match.size_category_id;
    }

    domainSelect.addEventListener("change", function () { refreshSubdomainUI(domainSelect.value); });

    if (employeesInput) {
      employeesInput.addEventListener("input", function () {
        if (employeesInput.value.trim() === "") manualSizeCategory = false;
        suggestSizeCategory();
      });
    }
    sizeSelect.addEventListener("change", function () { manualSizeCategory = sizeSelect.value !== ""; });

    fetch("/organizations/classification-tree")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        tree = data;

        fillSelect(sizeSelect, tree.size_categories, "size_category_id", "label", "— Select size —");
        if (initial.size_category_id) sizeSelect.value = initial.size_category_id;
        else suggestSizeCategory();

        fillSelect(domainSelect, tree.domains, "organization_domain_id", "label", "— Select domain —");
        if (initial.organization_domain_id) {
          domainSelect.value = initial.organization_domain_id;
          refreshSubdomainUI(initial.organization_domain_id, initial.organization_subdomain_id);
        } else {
          refreshSubdomainUI("");
        }
      })
      .catch(function () {
        fillSelect(sizeSelect, [], null, null, "— Unable to load —");
        fillSelect(domainSelect, [], null, null, "— Unable to load —");
        fillSelect(subdomainSelect, [], null, null, "— Unable to load —");
      });
  };
})();
