'use strict';

(function(){

var app = angular.module('dataiku.plugins.github', []);


app.controller("GithubConnectorController", function($scope){
	console.info("******************* LOADING CONTROLLER **************************")

	$scope.test = function(){
		$scope.callPythonDo({
			callType : "test"
		}).then(function(data){
			$scope.testData = data;
		})
	}
});

})();