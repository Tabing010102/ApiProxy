using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using OpenCCNET;
using System.Reflection;
using System.Text;

namespace ApiProxy
{
    public class Program
    {
        public static void Main(string[] args)
        {
            var builder = WebApplication.CreateSlimBuilder(args);
            builder.Logging.ClearProviders();
            builder.Logging.AddConsole();
            var app = builder.Build();

            // 读取配置文件
            var configuration = new ConfigurationBuilder()
                .AddJsonFile("appsettings.json")
                .Build();

            var proxySettings = configuration.GetSection("ProxySettings").Get<ProxySettings>();

            ZhConverter.Initialize();

            app.Use((context, next) =>
            {
                context.Request.EnableBuffering();
                return next(context);
            });

            app.MapPost(proxySettings.ProxyEndpoint, async (HttpRequest httpRequest, HttpResponse httpResponse, HttpClient httpClient, ILogger<Program> logger) =>
            {
                var targetUrl = proxySettings.TargetUrl; // 目标服务器的URL

                httpRequest.Body.Position = 0;
                using var reader = new StreamReader(httpRequest.Body, Encoding.UTF8);
                var requestBody = await reader.ReadToEndAsync();
                //var requestBody = await httpRequest.ReadFromJsonAsync<string>();

                logger.LogInformation("Received request body: {RequestBody}", requestBody);

                var content = new StringContent(requestBody, Encoding.UTF8, "application/json");
                var response = await httpClient.PostAsync(targetUrl, content);

                if (response.IsSuccessStatusCode)
                {
                    var responseContent = await response.Content.ReadAsStringAsync();
                    logger.LogInformation("Received response from target URL: {ResponseContent}", responseContent);

                    var traditionalChineseContent = ConvertText(responseContent, proxySettings.SourceLang, proxySettings.DestLang, proxySettings.IsIdiomConvert, logger);
                    httpResponse.ContentType = "application/json";
                    await httpResponse.WriteAsync(traditionalChineseContent, Encoding.UTF8);
                }
                else
                {
                    httpResponse.StatusCode = (int)response.StatusCode;
                    var errorContent = await response.Content.ReadAsStringAsync();
                    logger.LogError("Error response from target URL: {ErrorContent}", errorContent);
                    await httpResponse.WriteAsync(errorContent, Encoding.UTF8);
                }
            });

            app.Run();
        }

        private static string ConvertText(string text, string sourceLang, string destLang, bool isIdiomConvert, ILogger logger)
        {
            var methodName = $"{sourceLang}To{destLang}";
            var method = typeof(ZhConverter).GetMethod(methodName, BindingFlags.Public | BindingFlags.Static);

            if (method == null)
            {
                var errorMessage = $"Method {methodName} not found in ZhConverter.";
                logger.LogError(errorMessage);
                throw new InvalidOperationException(errorMessage);
            }

            var parameters = method.GetParameters();
            string result;

            if (parameters.Length == 1)
            {
                result = (string)method.Invoke(null, new object[] { text });
            }
            else if (parameters.Length == 2 && parameters[1].ParameterType == typeof(bool))
            {
                result = (string)method.Invoke(null, new object[] { text, isIdiomConvert });
            }
            else
            {
                var errorMessage = $"Method {methodName} has an unsupported signature.";
                logger.LogError(errorMessage);
                throw new InvalidOperationException(errorMessage);
            }

            logger.LogInformation("Converted text: {ConvertedText}", result);
            return result;
        }
    }

    public class ProxySettings
    {
        public string ProxyEndpoint { get; set; }
        public string TargetUrl { get; set; }
        public string SourceLang { get; set; }
        public string DestLang { get; set; }
        public bool IsIdiomConvert { get; set; }
    }
}
