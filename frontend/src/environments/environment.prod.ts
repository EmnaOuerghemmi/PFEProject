/**
 * Configuration de production.
 *
 * Les URL sont RELATIVES à l'origine servant l'application : nginx expose le
 * frontend et proxifie `/api/` vers le backend (cf. frontend/nginx.conf).
 *
 * Conséquence : la même image Docker fonctionne sur n'importe quel domaine —
 * recette, production, adresse IP — sans rebuild. C'est pourquoi le domaine
 * d'API n'est plus écrit en dur ici (il pointait vers `api.example.com`, une
 * valeur d'exemple qui n'aurait de toute façon pas fonctionné).
 *
 * `wsUrl` doit néanmoins être absolue (l'API WebSocket n'accepte pas de
 * chemin relatif) : on la dérive de l'origine courante pour choisir
 * automatiquement `ws://` en HTTP et `wss://` en HTTPS.
 */
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

export const environment = {
  production: true,
  apiUrl: '/api/v1',
  wsUrl: `${wsProtocol}//${window.location.host}/api/v1`,
  googleClientId: '137121157008-bskil5iiqp5i1qpddsf602recamg532k.apps.googleusercontent.com'
};
