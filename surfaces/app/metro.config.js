// Metro config — exists for exactly ONE reason: the cell UI units live at the
// REPO ROOT (cells/<id>/ui/, two-mains split + phase 3), outside this app
// folder, so Metro must (a) watch that tree and (b) resolve the `@cells/*`
// alias into it. Everything else is the Expo default. The app stays the ONE
// buildable project — cells ship UI *units*, never their own bundle.
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const projectRoot = __dirname;
const cellsRoot = path.resolve(projectRoot, "..", "..", "cells");

const config = getDefaultConfig(projectRoot);

config.watchFolders = [...(config.watchFolders ?? []), cellsRoot];
config.resolver.extraNodeModules = {
  ...(config.resolver.extraNodeModules ?? {}),
  "@cells": cellsRoot,
};
// Files under cells/ would walk UP from the repo root looking for node_modules
// and find none (it lives in app/, not at the root) - pin the lookup here.
config.resolver.nodeModulesPaths = [
  path.join(projectRoot, "node_modules"),
  ...(config.resolver.nodeModulesPaths ?? []),
];

module.exports = config;
