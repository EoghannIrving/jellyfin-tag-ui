import { setupServerConfigPersistence } from "./storage.js";
import { initializeSelection } from "./selection.js";
import { initializeTagPanel } from "./tags.js";
import { initializeApply } from "./apply.js";
import { initializeSearch } from "./search.js";

setupServerConfigPersistence();
initializeSelection();
initializeTagPanel();
initializeApply();
initializeSearch();
