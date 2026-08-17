const path = require("path");
const fs = require("fs");

module.exports = function ({ middlewareUtil }) {
    const nodeModulesRoot = path.join(__dirname, "..");
    return (req, res, next) => {
        if (!req.path.startsWith("/node_modules/")) return next();
        const filePath = path.join(nodeModulesRoot, req.path);
        if (!fs.existsSync(filePath)) return next();
        const { contentType } = middlewareUtil.getMimeInfo(req.path);
        res.setHeader("Content-Type", contentType);
        res.end(fs.readFileSync(filePath));
    };
};
