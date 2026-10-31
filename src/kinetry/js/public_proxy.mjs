// A small forward proxy for the brand probe's browser in service mode. Chrome sends it every request, by host
// name; the proxy resolves each name once, refuses it unless every address is public, and connects to the
// address it checked. Without it Chrome would do its own DNS lookup after our check, and a host that changes
// its answer in between (DNS rebinding) could reach internal addresses. Mirrors netguard.public_client.
import http from "node:http";
import net from "node:net";
import { lookup as dnsLookup } from "node:dns";

function blocked(host) {
  const e = new Error(`${host} resolves to a non-public address`);
  e.code = "EBLOCKED";
  return e;
}

// a `lookup` for net.connect / http.request that only ever hands back checked addresses
export function guardedLookup(isPublicIp, lookupFn = dnsLookup) {
  return (hostname, options, cb) => {
    if (typeof options === "function") [cb, options] = [options, {}];
    lookupFn(hostname, { all: true }, (err, addrs) => {
      if (err) return cb(err);
      if (!addrs || !addrs.length || !addrs.every((a) => isPublicIp(a.address))) return cb(blocked(hostname));
      if (options && options.all) return cb(null, addrs);
      cb(null, addrs[0].address, addrs[0].family);
    });
  };
}

function splitHostPort(s) {
  const m = s.match(/^\[([^\]]+)\]:(\d+)$/) || s.match(/^([^:]+):(\d+)$/);
  return m ? [m[1], Number(m[2])] : [s, 443];
}

export function startPublicProxy({ isPublicIp, lookupFn } = {}) {
  const lookup = guardedLookup(isPublicIp, lookupFn);
  // node skips `lookup` for IP literals, so check those directly
  const literalOk = (host) => !net.isIP(host) || isPublicIp(host);

  const server = http.createServer((req, res) => {
    let target;
    try {
      target = new URL(req.url);
    } catch {
      return res.writeHead(400).end();
    }
    const host = target.hostname.replace(/^\[|\]$/g, "");
    if (target.protocol !== "http:" || !literalOk(host)) return res.writeHead(403).end();
    const headers = { ...req.headers };
    delete headers["proxy-connection"];
    delete headers["proxy-authorization"];
    const up = http.request(
      { host, port: target.port || 80, path: target.pathname + target.search, method: req.method, headers, lookup },
      (r) => {
        res.writeHead(r.statusCode || 502, r.headers);
        r.pipe(res);
      },
    );
    up.on("error", () => {
      if (!res.headersSent) res.writeHead(502);
      res.end();
    });
    req.pipe(up);
  });

  server.on("connect", (req, sock, head) => {
    const [host, port] = splitHostPort(req.url || "");
    sock.on("error", () => {});
    if (!literalOk(host)) return sock.end("HTTP/1.1 403 Forbidden\r\n\r\n");
    const up = net.connect({ host, port, lookup }, () => {
      sock.write("HTTP/1.1 200 Connection Established\r\n\r\n");
      if (head && head.length) up.write(head);
      up.pipe(sock);
      sock.pipe(up);
    });
    up.on("error", () => sock.end("HTTP/1.1 502 Bad Gateway\r\n\r\n"));
    sock.on("close", () => up.destroy());
  });

  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port })));
}
