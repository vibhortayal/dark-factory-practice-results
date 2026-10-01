import { createServer } from './server.js';

process.on('uncaughtException', (e) => console.error('uncaught', e));
process.on('unhandledRejection', (e) => console.error('unhandled', e));

const port = Number(process.env.PORT) || 8080;
createServer().listen(port, '0.0.0.0', () => console.log(`pocketful listening on 0.0.0.0:${port}`));
