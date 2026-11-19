const base = require("./app.json").expo;
module.exports = () => {
  const preview = process.env.EXPO_PUBLIC_APP_VARIANT === "preview";
  return {
    ...base,
    name: preview ? "IMAGINE 체험" : base.name,
    android: {
      ...base.android,
      package: preview ? "com.storyverse.ai.preview" : base.android.package,
    },
  };
};
