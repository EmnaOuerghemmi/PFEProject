// Configuration Karma — identique à celle qu'Angular applique par défaut,
// plus un lanceur pour la CI.
//
// ChromeHeadlessCI : les runners Ubuntu 24.04 restreignent les espaces de
// noms utilisateur (AppArmor), ce qui empêche le bac à sable de Chrome de
// démarrer (« No usable sandbox »). Dans un conteneur jetable de CI, sans
// navigation vers des sites tiers, le désactiver est sans risque.
module.exports = function (config) {
  config.set({
    basePath: '',
    frameworks: ['jasmine', '@angular-devkit/build-angular'],
    plugins: [
      require('karma-jasmine'),
      require('karma-chrome-launcher'),
      require('karma-jasmine-html-reporter'),
      require('karma-coverage'),
      require('@angular-devkit/build-angular/plugins/karma'),
    ],
    client: {
      jasmine: {},
      clearContext: false,
    },
    jasmineHtmlReporter: { suppressAll: true },
    coverageReporter: {
      dir: require('path').join(__dirname, './coverage/frontend'),
      subdir: '.',
      reporters: [{ type: 'html' }, { type: 'text-summary' }, { type: 'lcovonly' }],
    },
    reporters: ['progress', 'kjhtml'],
    browsers: ['Chrome'],
    customLaunchers: {
      ChromeHeadlessCI: {
        base: 'ChromeHeadless',
        flags: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
      },
    },
    // Le premier chargement du bundle de test peut être long sur un runner partagé.
    browserNoActivityTimeout: 120000,
    restartOnFileChange: true,
  });
};
