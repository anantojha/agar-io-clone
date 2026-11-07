// Where the game server lives. Leave server empty when the same host serves this page and the
// game (the Docker image does). For the GitHub Pages copy, the deploy workflow overwrites this
// file with the server's wss:// address.
window.AGAR_CONFIG = {
  server: "wss://agar-clone-gt1z.onrender.com/ws",
};
