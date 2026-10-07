export const environment = {
  production: false,
  apiUrl: 'http://localhost:8000/api/v1',
  wsUrl: 'ws://localhost:8000/api/v1',
  // DOIT correspondre à GOOGLE_CLIENT_ID du backend : `report_service` vérifie
  // l'audience (`aud`) des jetons d'identité contre cette valeur. Deux ID
  // différents font échouer la connexion Google sans message explicite.
  // L'ID client n'est pas un secret — il part dans le bundle par conception.
  googleClientId: '1011808931250-rs16n7sn04luf2t0a7uhteakjp88tb2i.apps.googleusercontent.com'
};
