// Expo prebuild, uygulama adında Türkçe karakter olunca Kotlin paket adını bozuyor.
// Bu yüzden app.json'da "name" ASCII; telefonda görünen adı burada "TÜİK Cep" yapıyoruz.
const { withStringsXml, AndroidConfig } = require('expo/config-plugins');

module.exports = function withAndroidLabel(config, label) {
  return withStringsXml(config, (c) => {
    c.modResults = AndroidConfig.Strings.setStringItem(
      [{ $: { name: 'app_name', translatable: 'false' }, _: label }],
      c.modResults,
    );
    return c;
  });
};
